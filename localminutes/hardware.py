"""Universal hardware, CPU/SIMD/Apple Silicon detection, and cross-platform data path helpers."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

CT2_COMPUTE_PRIORITY: Tuple[str, ...] = (
    "int8",
    "int8_float32",
    "int16",
    "float32",
    "default",
)

PROFILE_AUTO = "auto"
PROFILE_ECO = "eco"
PROFILE_BALANCED = "balanced"
PROFILE_PERFORMANCE = "performance"
VALID_PROFILES = (PROFILE_AUTO, PROFILE_ECO, PROFILE_BALANCED, PROFILE_PERFORMANCE)


@dataclass(frozen=True)
class HardwareProfile:
    """Detected host hardware capabilities for adaptive Whisper CPU configuration."""

    os_name: str
    os_version: str
    arch: str
    cpu_name: str
    logical_cores: int
    physical_cores: int
    is_apple_silicon: bool = False
    isa_features: Tuple[str, ...] = field(default_factory=tuple)
    supported_ct2_types: Tuple[str, ...] = field(default_factory=tuple)
    recommended_tier: str = PROFILE_BALANCED

    @property
    def has_modern_simd(self) -> bool:
        feats = set(self.isa_features)
        return bool(
            feats.intersection(
                {"avx2", "avx512f", "avx_vnni", "avx512_vnni", "neon", "dotprod"}
            )
        )

    @property
    def short_cpu_label(self) -> str:
        name = " ".join(self.cpu_name.split())
        if len(name) > 42:
            name = name[:39] + "..."
        return name or f"{self.arch.upper()} CPU"


@dataclass(frozen=True)
class RuntimeTuning:
    """Optimal CPU threading and CTranslate2 compute-type fallback order."""

    requested_profile: str
    effective_profile: str
    whisper_threads: int
    compute_type_candidates: Tuple[str, ...]


def normalize_arch(raw_machine: Optional[str] = None) -> str:
    m = (raw_machine or platform.machine() or "").strip().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if m in ("arm64", "aarch64", "armv8", "armv8l"):
        return "arm64"
    if m in ("i386", "i686", "x86"):
        return "x86"
    return m or "unknown"


def detect_cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                if val and str(val).strip():
                    return " ".join(str(val).strip().split())
        except Exception:
            pass

    if sys.platform.startswith("linux"):
        try:
            fallback_arm: Optional[str] = None
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if ":" not in line:
                        continue
                    key, val = line.split(":", 1)
                    k = key.strip().lower()
                    v = " ".join(val.strip().split())
                    if not v:
                        continue
                    if k == "model name":
                        return v
                    if k in ("hardware", "model") and not v.isdigit() and fallback_arm is None:
                        fallback_arm = v
            if fallback_arm:
                return fallback_arm
        except Exception:
            pass

    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return " ".join(res.stdout.strip().split())
        except Exception:
            pass

    fallback = (platform.processor() or "").strip()
    if fallback:
        return " ".join(fallback.split())
    return f"{normalize_arch().upper()} Processor"


def detect_physical_cores(logical_cores: int) -> int:
    logical = max(1, int(logical_cores))

    if sys.platform.startswith("linux"):
        try:
            pairs: Set[Tuple[str, str]] = set()
            phys_id = "0"
            core_id: Optional[str] = None
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        if core_id is not None:
                            pairs.add((phys_id, core_id))
                        phys_id = "0"
                        core_id = None
                        continue
                    if ":" in stripped:
                        k, v = [p.strip() for p in stripped.split(":", 1)]
                        if k == "physical id":
                            phys_id = v
                        elif k == "core id":
                            core_id = v
                if core_id is not None:
                    pairs.add((phys_id, core_id))
            if pairs:
                return max(1, min(logical, len(pairs)))
        except Exception:
            pass

    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["sysctl", "-n", "hw.physicalcpu"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip().isdigit():
                return max(1, min(logical, int(res.stdout.strip())))
        except Exception:
            pass

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            get_lpi = kernel32.GetLogicalProcessorInformationEx
            get_lpi.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
            get_lpi.restype = wintypes.BOOL
            relation_processor_core = 0
            buf_len = wintypes.DWORD(0)
            get_lpi(relation_processor_core, None, ctypes.byref(buf_len))
            if buf_len.value > 0:
                buf = ctypes.create_string_buffer(buf_len.value)
                ok = get_lpi(relation_processor_core, buf, ctypes.byref(buf_len))
                if ok:
                    raw = buf.raw
                    offset = 0
                    cores = 0
                    while offset + 8 <= buf_len.value:
                        rel = int.from_bytes(raw[offset : offset + 4], "little")
                        size = int.from_bytes(raw[offset + 4 : offset + 8], "little")
                        if size <= 0:
                            break
                        if rel == relation_processor_core:
                            cores += 1
                        offset += size
                    if cores > 0:
                        return max(1, min(logical, cores))
        except Exception:
            pass

    if logical <= 2:
        return logical
    return max(2, logical // 2)


def detect_isa_features(arch: Optional[str] = None) -> Tuple[str, ...]:
    norm_arch = normalize_arch(arch)
    found: Set[str] = set()

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            is_feat = ctypes.windll.kernel32.IsProcessorFeaturePresent
            is_feat.argtypes = [wintypes.DWORD]
            is_feat.restype = wintypes.BOOL
            win_flags = (
                (10, "sse2"),
                (37, "sse4_1"),
                (38, "sse4_2"),
                (39, "avx"),
                (40, "avx2"),
                (41, "avx512f"),
                (19, "neon"),  # PF_ARM_NEON_INSTRUCTIONS_AVAILABLE
                (43, "dotprod"),
            )
            for code, name in win_flags:
                try:
                    if bool(is_feat(code)):
                        found.add(name)
                except Exception:
                    pass
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    lower = line.lower()
                    if lower.startswith(("flags", "features")) and ":" in lower:
                        tokens = set(lower.split(":", 1)[1].split())
                        flag_map = {
                            "sse2": "sse2",
                            "sse4_1": "sse4_1",
                            "sse4_2": "sse4_2",
                            "avx": "avx",
                            "avx2": "avx2",
                            "avx512f": "avx512f",
                            "avx512_vnni": "avx512_vnni",
                            "avx_vnni": "avx_vnni",
                            "asimd": "neon",
                            "neon": "neon",
                            "asimddp": "dotprod",
                        }
                        for src_flag, norm_name in flag_map.items():
                            if src_flag in tokens:
                                found.add(norm_name)
                        break
        except Exception:
            pass
    elif sys.platform == "darwin":
        if norm_arch == "arm64":
            found.update({"neon", "dotprod"})
        else:
            for sysctl_key, feat_name in (
                ("hw.optional.sse4_2", "sse4_2"),
                ("hw.optional.avx1_0", "avx"),
                ("hw.optional.avx2_0", "avx2"),
                ("hw.optional.avx512f", "avx512f"),
            ):
                try:
                    res = subprocess.run(
                        ["sysctl", "-n", sysctl_key],
                        capture_output=True,
                        text=True,
                        timeout=1,
                        check=False,
                    )
                    if res.returncode == 0 and res.stdout.strip() == "1":
                        found.add(feat_name)
                except Exception:
                    pass

    return tuple(sorted(found))


def query_ct2_supported_compute_types() -> Tuple[str, ...]:
    """Query CTranslate2 for supported CPU compute types safely."""
    try:
        import ctranslate2

        supported = ctranslate2.get_supported_compute_types("cpu")
        if supported:
            return tuple(sorted(str(x).lower() for x in supported))
    except Exception:
        pass
    return ()


def select_compute_type_candidates(
    preferred: str = "int8",
    supported_types: Sequence[str] = (),
) -> Tuple[str, ...]:
    """Order CTranslate2 compute types starting from `preferred` then falling back safely."""
    supported_set = {str(x).lower() for x in supported_types}
    ordered: List[str] = []

    pref = (preferred or "int8").strip().lower()
    if pref and (not supported_set or pref in supported_set or pref in ("auto", "default")):
        ordered.append(pref)

    if supported_set:
        for candidate in CT2_COMPUTE_PRIORITY:
            if (candidate in supported_set or candidate == "default") and candidate not in ordered:
                ordered.append(candidate)
        for extra in sorted(supported_set):
            if extra not in ordered and extra != "auto":
                ordered.append(extra)
    else:
        for candidate in CT2_COMPUTE_PRIORITY:
            if candidate not in ordered:
                ordered.append(candidate)

    if "float32" not in ordered:
        ordered.append("float32")
    if "auto" not in ordered:
        ordered.append("auto")
    return tuple(ordered)


def classify_hardware_tier(
    logical_cores: int,
    physical_cores: int,
    isa_features: Sequence[str],
    arch: str,
) -> str:
    feats = set(isa_features)
    has_modern = bool(
        feats.intersection({"avx2", "avx512f", "avx_vnni", "avx512_vnni", "neon", "dotprod"})
    )
    if physical_cores >= 6 and logical_cores >= 8 and (has_modern or not feats):
        return PROFILE_PERFORMANCE
    if physical_cores <= 2 or logical_cores <= 2:
        return PROFILE_ECO
    if arch == "x86_64" and feats and not has_modern and physical_cores <= 4:
        return PROFILE_ECO
    return PROFILE_BALANCED


def detect_hardware_profile(query_ct2: bool = True) -> HardwareProfile:
    os_name = platform.system() or sys.platform
    os_version = platform.release() or ""
    arch = normalize_arch()
    cpu_name = detect_cpu_name()
    logical = max(1, os.cpu_count() or 2)
    physical = detect_physical_cores(logical)
    isa = detect_isa_features(arch)
    ct2_types = query_ct2_supported_compute_types() if query_ct2 else ()
    is_apple_silicon = sys.platform == "darwin" and arch == "arm64"
    tier = classify_hardware_tier(logical, physical, isa, arch)

    return HardwareProfile(
        os_name=os_name,
        os_version=os_version,
        arch=arch,
        cpu_name=cpu_name,
        logical_cores=logical,
        physical_cores=physical,
        is_apple_silicon=is_apple_silicon,
        isa_features=isa,
        supported_ct2_types=ct2_types,
        recommended_tier=tier,
    )


def compute_runtime_tuning(
    hw: HardwareProfile,
    requested_profile: str = PROFILE_AUTO,
    preferred_compute_type: str = "int8",
) -> RuntimeTuning:
    req = requested_profile if requested_profile in VALID_PROFILES else PROFILE_AUTO
    eff = hw.recommended_tier if req == PROFILE_AUTO else req
    safe_max = max(1, hw.logical_cores - 1) if hw.logical_cores >= 2 else 1

    if eff == PROFILE_ECO:
        threads = max(1, min(2, hw.physical_cores, safe_max))
    elif eff == PROFILE_PERFORMANCE:
        threads = max(2, min(8, hw.physical_cores, safe_max))
    else:
        threads = max(2, min(4, hw.physical_cores, safe_max))

    candidates = select_compute_type_candidates(
        preferred=preferred_compute_type,
        supported_types=hw.supported_ct2_types,
    )
    return RuntimeTuning(
        requested_profile=req,
        effective_profile=eff,
        whisper_threads=threads,
        compute_type_candidates=candidates,
    )


def apply_thread_env_defaults(tuning: RuntimeTuning) -> None:
    t = str(max(1, tuning.whisper_threads))
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ.setdefault(var, t)


def get_app_base_dir() -> str:
    """Return the application root directory whether running from source or PyInstaller."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_writable_data_dir(override: Optional[str] = None) -> Path:
    """
    Return the persistent OS-native writable data directory for LocalMinutes:
      - Env override: LOCALMINUTES_DATA_DIR
      - Windows: %APPDATA%/LocalMinutes
      - macOS: ~/Library/Application Support/LocalMinutes
      - Linux: $XDG_DATA_HOME/localminutes (default ~/.local/share/localminutes)
    """
    env_override = override or os.environ.get("LOCALMINUTES_DATA_DIR")
    if env_override:
        base = Path(env_override)
    elif sys.platform == "win32":
        root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home())
        base = Path(root) / "LocalMinutes"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "LocalMinutes"
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        base = Path(xdg) / "localminutes"

    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        import tempfile

        base = Path(tempfile.gettempdir()) / "localminutes"
        base.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(base, 0o700)
        except OSError:
            pass
    return base


def get_ct2_safe_path(model_dir: str) -> str:
    """Work around Windows Unicode path issues in CTranslate2 C++ loaders."""
    try:
        model_dir.encode("ascii")
        return model_dir
    except UnicodeEncodeError:
        pass

    try:
        rel = os.path.relpath(model_dir)
        rel.encode("ascii")
        return rel
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            get_short = ctypes.windll.kernel32.GetShortPathNameW
            get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            get_short.restype = wintypes.DWORD
            buf = ctypes.create_unicode_buffer(1024)
            res = get_short(model_dir, buf, len(buf))
            if 0 < res < len(buf):
                short_path = buf.value
                short_path.encode("ascii")
                return short_path
        except Exception:
            pass

    return model_dir


def get_ui_font_family() -> str:
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "SF Pro Display"
    return "DejaVu Sans"


def get_mono_font_family() -> str:
    if sys.platform == "win32":
        return "Cascadia Mono"
    if sys.platform == "darwin":
        return "SF Mono"
    return "DejaVu Sans Mono"


def format_hardware_summary(hw: HardwareProfile, tuning: RuntimeTuning, lang: str = "en") -> str:
    tier_map: Dict[str, Dict[str, str]] = {
        "en": {
            PROFILE_ECO: "Eco",
            PROFILE_BALANCED: "Balanced",
            PROFILE_PERFORMANCE: "Performance",
        },
        "tr": {
            PROFILE_ECO: "Eko",
            PROFILE_BALANCED: "Dengeli",
            PROFILE_PERFORMANCE: "Yüksek Performans",
        },
    }
    labels = tier_map.get(lang, tier_map["en"])
    tier_txt = labels.get(tuning.effective_profile, tuning.effective_profile)
    simd_str = ", ".join(f.upper() for f in hw.isa_features) if hw.isa_features else "Standard"
    best_ct = (tuning.compute_type_candidates[0] if tuning.compute_type_candidates else "int8").upper()
    return (
        f"{hw.short_cpu_label} ({hw.physical_cores}C/{hw.logical_cores}T, {hw.arch})  ·  "
        f"{tier_txt}  ·  {best_ct} ({tuning.whisper_threads}T)  ·  ISA: {simd_str}  ·  0 MB VRAM"
    )
