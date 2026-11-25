"""Application configuration and OS-native local storage paths."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from localminutes.hardware import VALID_PROFILES, get_writable_data_dir
from localminutes.models import SUMMARY_TEMPLATES, AppSettings

_VALID_UI_LANGS = frozenset({"en", "tr"})
_VALID_LLM_PROVIDERS = frozenset({"auto", "ollama", "openai_compatible", "local_extractive"})


def get_data_dir() -> Path:
    """Return the persistent OS-native local data directory for LocalMinutes."""
    return get_writable_data_dir()


def get_db_path() -> Path:
    return get_data_dir() / "localminutes.db"


def get_models_dir() -> Path:
    path = get_data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_recordings_dir() -> Path:
    path = get_data_dir() / "recordings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_config_path() -> Path:
    return get_data_dir() / "settings.json"


def get_crash_log_path() -> Path:
    return get_data_dir() / "crash.log"


def _clamp_int(val: Any, lo: int, hi: int, default: int) -> int:
    try:
        if isinstance(val, bool):
            return default
        num = int(val)
        return max(lo, min(hi, num))
    except (TypeError, ValueError):
        return default


def _clamp_float(val: Any, lo: float, hi: float, default: float) -> float:
    try:
        if isinstance(val, bool):
            return default
        num = float(val)
        if not math.isfinite(num):
            return default
        return max(lo, min(hi, num))
    except (TypeError, ValueError):
        return default


def _safe_optional_dev_idx(val: Any) -> int | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        idx = int(val)
        return idx if idx >= 0 else None
    except (TypeError, ValueError):
        return None


def _safe_str(val: Any, default: str) -> str:
    if isinstance(val, str):
        return val
    return default


def _sanitize_settings(raw: dict[str, Any]) -> AppSettings:
    defaults = asdict(AppSettings())
    merged: dict[str, Any] = {k: raw.get(k, v) for k, v in defaults.items()}

    ui_lang = _safe_str(merged["ui_language"], defaults["ui_language"]).strip().lower()
    merged["ui_language"] = ui_lang if ui_lang in _VALID_UI_LANGS else defaults["ui_language"]

    perf = _safe_str(merged["performance_profile"], defaults["performance_profile"]).strip().lower()
    merged["performance_profile"] = perf if perf in VALID_PROFILES else defaults["performance_profile"]

    provider = _safe_str(merged["llm_provider"], defaults["llm_provider"]).strip().lower()
    merged["llm_provider"] = provider if provider in _VALID_LLM_PROVIDERS else defaults["llm_provider"]

    tmpl = _safe_str(merged["default_template"], defaults["default_template"]).strip().lower()
    merged["default_template"] = tmpl if tmpl in SUMMARY_TEMPLATES else defaults["default_template"]

    for bool_key in (
        "air_gapped_mode",
        "check_updates_on_startup",
        "minimize_to_tray",
        "capture_mic",
        "capture_loopback",
        "save_wav",
    ):
        val = merged[bool_key]
        merged[bool_key] = bool(val) if isinstance(val, (bool, int)) else bool(defaults[bool_key])

    merged["mic_device_index"] = _safe_optional_dev_idx(merged["mic_device_index"])
    merged["loopback_device_index"] = _safe_optional_dev_idx(merged["loopback_device_index"])

    merged["vad_silence_ms"] = _clamp_int(merged["vad_silence_ms"], 100, 10_000, defaults["vad_silence_ms"])
    merged["chunk_max_sec"] = _clamp_float(merged["chunk_max_sec"], 1.0, 120.0, defaults["chunk_max_sec"])
    merged["energy_threshold"] = _clamp_float(
        merged["energy_threshold"], 0.0001, 0.5, defaults["energy_threshold"]
    )

    for str_key in (
        "whisper_model",
        "whisper_compute_type",
        "whisper_language",
        "custom_vocabulary",
        "ollama_url",
        "ollama_model",
        "api_base_url",
        "api_key",
        "api_model",
        "summary_language",
    ):
        merged[str_key] = _safe_str(merged[str_key], defaults[str_key])

    return AppSettings(**merged)


def load_settings() -> AppSettings:
    """Load settings from JSON, clamping numeric bounds and falling back safely on corruption."""
    path = get_config_path()
    if not path.exists():
        return AppSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return AppSettings()
        return _sanitize_settings(raw)
    except Exception:
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    """Persist settings to JSON atomically with restrictive POSIX permissions (0o600)."""
    sanitized = _sanitize_settings(asdict(settings))
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass

    payload = json.dumps(asdict(sanitized), ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=".settings_", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        if os.name == "posix":
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                pass
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path)
        if os.name == "posix":
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
