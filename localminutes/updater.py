"""Cross-platform GitHub Releases SemVer auto-updater for LocalMinutes."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from localminutes import __app_name__, __repo__, __version__

GITHUB_LATEST_RELEASE_URL = f"https://api.github.com/repos/{__repo__}/releases/latest"

ALLOWED_UPDATE_HOSTS = frozenset(
    {
        "github.com",
        "api.github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)

_ORIG_URLOPEN = urllib.request.urlopen

_ARM64_ARCH_TOKENS = ("arm64", "aarch64", "apple-silicon", "apple_silicon")
_X64_ARCH_TOKENS = ("x86_64", "amd64", "x64", "win64", "intel")
_UNIVERSAL_ARCH_TOKENS = ("universal", "universal2")


def validate_update_url(url: str) -> str:
    """Enforce HTTPS and strict GitHub release host allowlist."""
    cleaned = (url or "").strip()
    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme.lower() != "https":
        raise ValueError(f"Blocked non-HTTPS update URL: {cleaned}")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_UPDATE_HOSTS:
        raise ValueError(f"Blocked untrusted update host '{host}': {cleaned}")
    if parsed.username or parsed.password:
        raise ValueError(f"Blocked update URL with embedded credentials: {cleaned}")
    return cleaned


class _AllowedHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validate every HTTP redirect hop against the HTTPS + GitHub host allowlist."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        resolved = urllib.parse.urljoin(req.full_url, newurl)
        validate_update_url(resolved)
        return super().redirect_request(req, fp, code, msg, headers, resolved)


def _open_validated_url(req: urllib.request.Request, timeout: float):
    """Open an allowlisted HTTPS GitHub URL with strict redirect validation."""
    validate_update_url(req.full_url)
    if urllib.request.urlopen is not _ORIG_URLOPEN:
        # Respect unit test patches on localminutes.updater.urllib.request.urlopen
        resp = urllib.request.urlopen(req, timeout=timeout)
    else:
        opener = urllib.request.build_opener(_AllowedHostRedirectHandler())
        resp = opener.open(req, timeout=timeout)
    final_url = getattr(resp, "geturl", None)
    if callable(final_url):
        resolved = final_url()
        if isinstance(resolved, str) and resolved:
            validate_update_url(resolved)
    return resp


@dataclass(frozen=True)
class UpdateInfo:
    """Result of checking GitHub Releases for a newer LocalMinutes build."""

    current_version: str
    latest_version: str
    is_update_available: bool
    release_url: str
    release_notes: str = ""
    error: Optional[str] = None
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    checksum_url: str = ""

    @property
    def has_direct_installer(self) -> bool:
        return bool(self.asset_url and self.asset_name)


def _parse_semver_full(
    version_str: str,
) -> Tuple[int, int, int, int, Tuple[Tuple[int, object], ...]]:
    """Parse SemVer 2.0.0 string -> (major, minor, patch, is_stable, prerelease_key)."""
    cleaned = (version_str or "").strip().lstrip("vV")
    # Build metadata (+...) MUST be ignored for precedence and never mistaken for prerelease (-).
    core_and_pre = cleaned.split("+", 1)[0]
    match = re.match(
        r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?$",
        core_and_pre,
    )
    if not match:
        return (0, 0, 0, 0, ())
    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    pre_str = match.group(4)
    if not pre_str:
        return (major, minor, patch, 1, ())
    pre_parts: List[Tuple[int, object]] = []
    for ident in pre_str.split("."):
        if ident.isdigit():
            # SemVer 2.0.0: numeric identifiers compare numerically and sort below alphanumeric
            pre_parts.append((0, int(ident)))
        else:
            pre_parts.append((1, ident))
    return (major, minor, patch, 0, tuple(pre_parts))


def parse_semver(version_str: str) -> Tuple[int, int, int, int]:
    """Parse SemVer string like 'v1.0.0' or '1.0.0-rc.1' -> (major, minor, patch, is_stable)."""
    major, minor, patch, is_stable, _ = _parse_semver_full(version_str)
    return (major, minor, patch, is_stable)


def is_newer_version(latest: str, current: str) -> bool:
    """Return True if `latest` is strictly newer than `current` under SemVer 2.0.0."""
    return _parse_semver_full(latest) > _parse_semver_full(current)


def _is_arch_mismatch(asset_name_low: str, is_arm64: bool, is_x64: bool) -> bool:
    """Return True if an asset explicitly targets an incompatible CPU architecture."""
    if any(tok in asset_name_low for tok in _UNIVERSAL_ARCH_TOKENS):
        return False
    has_arm = any(tok in asset_name_low for tok in _ARM64_ARCH_TOKENS)
    has_x64 = any(tok in asset_name_low for tok in _X64_ARCH_TOKENS)
    if is_arm64 and has_x64 and not has_arm:
        return True
    if is_x64 and has_arm and not has_x64:
        return True
    return False


def select_platform_asset(
    assets: List[Dict],
    platform_name: Optional[str] = None,
    machine: Optional[str] = None,
) -> Tuple[str, str, int, str]:
    """Select the best installer asset and matching SHA256SUMS URL for the OS/arch."""
    if not isinstance(assets, list):
        return ("", "", 0, "")

    plat = (platform_name or sys.platform).lower()
    arch = (machine or platform.machine() or "").lower()
    is_arm64 = arch in ("arm64", "aarch64")
    is_x64 = arch in ("x86_64", "amd64", "x64")

    best_asset: Optional[Dict] = None
    best_score = -1
    checksum_platform = ""
    checksum_generic = ""

    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("browser_download_url") or "").strip()
        if not name or not url:
            continue
        low = name.lower()

        if "sha256" in low and low.endswith(".txt"):
            if plat == "darwin" and ("macos" in low or "darwin" in low):
                checksum_platform = url
            elif plat == "win32" and ("win" in low or "windows" in low):
                checksum_platform = url
            elif plat.startswith("linux") and "linux" in low:
                checksum_platform = url
            elif not any(tag in low for tag in ("macos", "darwin", "win", "windows", "linux")):
                checksum_generic = url
            continue

        if _is_arch_mismatch(low, is_arm64=is_arm64, is_x64=is_x64):
            continue

        score = -1
        if plat == "darwin":
            if low.endswith(".dmg"):
                score = 10
                if is_arm64 and any(t in low for t in _ARM64_ARCH_TOKENS):
                    score = 30
                elif is_x64 and any(t in low for t in _X64_ARCH_TOKENS):
                    score = 30
                elif any(t in low for t in _UNIVERSAL_ARCH_TOKENS):
                    score = 20
        elif plat == "win32":
            if low.endswith(".exe"):
                score = 30 if "setup" in low else 15
            elif low.endswith(".zip") and "portable" in low:
                score = 10
        elif plat.startswith("linux"):
            if low.endswith(".appimage"):
                score = 30
            elif low.endswith(".tar.gz"):
                score = 20

        if score > best_score:
            best_score = score
            best_asset = item

    if not best_asset:
        return ("", "", 0, "")

    checksum_url = checksum_platform or checksum_generic
    return (
        str(best_asset.get("name") or ""),
        str(best_asset.get("browser_download_url") or ""),
        int(best_asset.get("size") or 0),
        checksum_url,
    )


def parse_sha256sums(sums_text: str, target_filename: str) -> Optional[str]:
    """Extract expected lowercase SHA-256 hex digest for `target_filename`."""
    target_base = os.path.basename(target_filename).strip().lower()
    for line in (sums_text or "").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            digest = parts[0].strip().lower()
            fname = os.path.basename(parts[-1].lstrip("*")).strip().lower()
            if fname == target_base and re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    return None


def compute_file_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def verify_file_sha256(file_path: str, expected_hex: str) -> bool:
    if not expected_hex or not os.path.isfile(file_path):
        return False
    return compute_file_sha256(file_path) == expected_hex.strip().lower()


def check_for_updates(
    current_version: str = __version__,
    api_url: str = GITHUB_LATEST_RELEASE_URL,
    timeout_sec: float = 5.0,
) -> UpdateInfo:
    """Query GitHub Releases API for latest version. Never raises on network failure."""
    fallback_release_url = f"https://github.com/{__repo__}/releases/latest"
    try:
        validate_update_url(api_url)
        req = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"{__app_name__}/{current_version}",
            },
        )
        with _open_validated_url(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        tag_name = str(payload.get("tag_name") or "").strip()
        latest_ver = tag_name.lstrip("vV") or current_version
        raw_html_url = str(payload.get("html_url") or fallback_release_url)
        try:
            html_url = validate_update_url(raw_html_url)
        except ValueError:
            html_url = fallback_release_url
        notes = str(payload.get("body") or "").strip()[:800]
        asset_name, asset_url, asset_size, checksum_url = select_platform_asset(
            payload.get("assets") or []
        )
        return UpdateInfo(
            current_version=current_version,
            latest_version=latest_ver,
            is_update_available=is_newer_version(latest_ver, current_version),
            release_url=html_url,
            release_notes=notes,
            asset_name=asset_name,
            asset_url=asset_url,
            asset_size=asset_size,
            checksum_url=checksum_url,
        )
    except Exception as exc:
        return UpdateInfo(
            current_version=current_version,
            latest_version=current_version,
            is_update_available=False,
            release_url=fallback_release_url,
            error=str(exc),
        )


def download_update_asset(
    info: UpdateInfo,
    dest_dir: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    status_cb: Optional[Callable[[str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    timeout_sec: float = 20.0,
) -> str:
    """Download the platform installer from GitHub, enforce fail-closed SHA-256 verification, and return final path."""
    if not info.has_direct_installer:
        raise RuntimeError("No direct installer asset found for this platform.")
    if not info.checksum_url:
        raise RuntimeError("Update refused: release is missing a SHA-256 checksum manifest.")

    validate_update_url(info.asset_url)
    validate_update_url(info.checksum_url)

    os.makedirs(dest_dir, exist_ok=True)
    safe_name = os.path.basename(info.asset_name)
    final_path = os.path.join(dest_dir, safe_name)
    part_path = final_path + ".part"

    req = urllib.request.Request(
        info.asset_url,
        headers={"User-Agent": f"{__app_name__}/{info.current_version}"},
    )
    downloaded = 0
    total = int(info.asset_size or 0)

    try:
        with _open_validated_url(req, timeout=timeout_sec) as resp:
            if total <= 0:
                hdr_len = resp.headers.get("Content-Length")
                if hdr_len and hdr_len.isdigit():
                    total = int(hdr_len)
            with open(part_path, "wb") as out:
                while True:
                    if cancel_check and cancel_check():
                        raise RuntimeError("Update download cancelled.")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)

        if status_cb:
            status_cb("Verifying SHA-256 checksum...")
        cs_req = urllib.request.Request(
            info.checksum_url,
            headers={"User-Agent": f"{__app_name__}/{info.current_version}"},
        )
        try:
            with _open_validated_url(cs_req, timeout=10.0) as cs_resp:
                sums_text = cs_resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch SHA-256 checksum manifest: {exc}") from exc

        expected = parse_sha256sums(sums_text, safe_name)
        if not expected:
            raise RuntimeError(f"SHA-256 checksum entry missing for '{safe_name}'.")
        if not verify_file_sha256(part_path, expected):
            raise RuntimeError("SHA-256 verification failed for downloaded installer.")

        os.replace(part_path, final_path)
        return final_path
    except Exception:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
        raise


def _find_running_macos_app_bundle() -> Optional[str]:
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    exe = os.path.abspath(sys.executable)
    marker = ".app/Contents/"
    idx = exe.find(marker)
    if idx == -1:
        return None
    return exe[: idx + 4]


def apply_downloaded_update(installer_path: str) -> Tuple[bool, str]:
    """Launch platform-native update installation. Returns (should_exit_app, message)."""
    if not os.path.isfile(installer_path):
        return (False, f"Installer not found: {installer_path}")

    if sys.platform == "win32":
        low = installer_path.lower()
        if low.endswith(".exe"):
            cmd = [installer_path]
            if "setup" in os.path.basename(low):
                cmd.extend(["/SP-", "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"])
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
            subprocess.Popen(cmd, creationflags=creationflags, close_fds=True)
            return (True, "Windows installer launched. LocalMinutes will update and restart.")
        os.startfile(installer_path)  # type: ignore[attr-defined]
        return (False, "Update archive opened.")

    if sys.platform == "darwin":
        app_bundle = _find_running_macos_app_bundle()
        if (
            app_bundle
            and installer_path.lower().endswith(".dmg")
            and os.access(os.path.dirname(app_bundle), os.W_OK)
        ):
            pid = os.getpid()
            script_fd, script_path = tempfile.mkstemp(prefix="localminutes_updater_", suffix=".sh")
            mount_dir = tempfile.mkdtemp(prefix="localminutes_mnt_")
            q_dmg = shlex.quote(installer_path)
            q_app = shlex.quote(app_bundle)
            q_app_new = shlex.quote(app_bundle + ".new")
            q_app_old = shlex.quote(app_bundle + ".old")
            q_mnt = shlex.quote(mount_dir)
            q_script = shlex.quote(script_path)

            script_body = f"""#!/bin/bash
set -euo pipefail
OLD_PID={pid}
WAITED=0
MAX_WAIT=100
while kill -0 "$OLD_PID" 2>/dev/null; do
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        exit 1
    fi
    sleep 0.3
    WAITED=$((WAITED + 1))
done

SWAPPED=0
cleanup() {{
    local rc=$?
    if [ "$rc" -ne 0 ] && [ "$SWAPPED" -eq 1 ] && [ ! -d {q_app} ] && [ -d {q_app_old} ]; then
        mv {q_app_old} {q_app} 2>/dev/null || true
    fi
    if [ "$rc" -ne 0 ] && [ -d {q_app_new} ]; then
        rm -rf {q_app_new} 2>/dev/null || true
    fi
    hdiutil detach {q_mnt} -quiet 2>/dev/null || true
    rmdir {q_mnt} 2>/dev/null || true
    rm -f {q_script} 2>/dev/null || true
}}
trap cleanup EXIT

hdiutil attach {q_dmg} -nobrowse -quiet -mountpoint {q_mnt}
SRC_APP="$(find {q_mnt} -maxdepth 1 -name '*.app' -print -quit)"
if [ -z "$SRC_APP" ]; then
    open {q_dmg}
    exit 1
fi

rm -rf {q_app_new} {q_app_old}
ditto "$SRC_APP" {q_app_new}
xattr -dr com.apple.quarantine {q_app_new} 2>/dev/null || true

if [ -d {q_app} ]; then
    mv {q_app} {q_app_old}
    SWAPPED=1
fi
mv {q_app_new} {q_app}
SWAPPED=0
rm -rf {q_app_old}
rm -f {q_dmg} 2>/dev/null || true

open -n {q_app}
"""
            with os.fdopen(script_fd, "w", encoding="utf-8") as f:
                f.write(script_body)
            os.chmod(script_path, 0o700)
            subprocess.Popen(
                ["/bin/bash", script_path],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            return (True, "Applying macOS update. LocalMinutes will relaunch shortly.")

        subprocess.Popen(["open", installer_path], start_new_session=True)
        return (False, "DMG opened in Finder. Drag LocalMinutes to Applications.")

    opener = shutil.which("xdg-open")
    if opener:
        subprocess.Popen([opener, installer_path], start_new_session=True)
    return (False, f"Update downloaded: {installer_path}")


try:
    from PyQt6.QtCore import QThread, pyqtSignal

    class UpdateCheckerThread(QThread):
        """Asynchronous GitHub Release update checker thread."""

        update_checked = pyqtSignal(object)

        def __init__(self, current_version: str = __version__, parent=None) -> None:
            super().__init__(parent)
            self.current_version = current_version

        def run(self) -> None:
            self.update_checked.emit(check_for_updates(current_version=self.current_version))

    class UpdateDownloadThread(QThread):
        """Asynchronous update installer downloader with SHA-256 verification."""

        progress_changed = pyqtSignal(int, int)
        status_changed = pyqtSignal(str)
        download_finished = pyqtSignal(str, str)

        def __init__(self, info: UpdateInfo, dest_dir: str, parent=None) -> None:
            super().__init__(parent)
            self.info = info
            self.dest_dir = dest_dir
            self._cancelled = False

        def cancel(self) -> None:
            self._cancelled = True

        def run(self) -> None:
            try:
                path = download_update_asset(
                    info=self.info,
                    dest_dir=self.dest_dir,
                    progress_cb=lambda dl, tot: self.progress_changed.emit(int(dl), int(tot)),
                    status_cb=lambda msg: self.status_changed.emit(str(msg)),
                    cancel_check=lambda: self._cancelled,
                )
                self.download_finished.emit(path, "")
            except Exception as exc:
                self.download_finished.emit("", str(exc))

except Exception:  # pragma: no cover
    UpdateCheckerThread = None  # type: ignore[assignment,misc]
    UpdateDownloadThread = None  # type: ignore[assignment,misc]
