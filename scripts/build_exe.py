#!/usr/bin/env python3
"""LocalMinutes — Windows x64 Standalone PyInstaller (--onedir) & Portable ZIP Builder.

Usage:
    python scripts/build_exe.py
    python scripts/build_exe.py --version 1.0.0
    python scripts/build_exe.py --skip-zip
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

APP_NAME = "LocalMinutes"
DEFAULT_VERSION = "1.0.0"

HIDDEN_IMPORTS = [
    "localminutes",
    "localminutes.analytics",
    "localminutes.app",
    "localminutes.config",
    "localminutes.hardware",
    "localminutes.i18n",
    "localminutes.models",
    "localminutes.updater",
    "localminutes.audio",
    "localminutes.audio.capture",
    "localminutes.audio.devices",
    "localminutes.export",
    "localminutes.export.exporter",
    "localminutes.storage",
    "localminutes.storage.database",
    "localminutes.summarization",
    "localminutes.summarization.local_extractive",
    "localminutes.summarization.qa",
    "localminutes.summarization.summarizer",
    "localminutes.transcription",
    "localminutes.transcription.engine",
    "localminutes.transcription.file_transcriber",
    "localminutes.transcription.live_pipeline",
    "localminutes.ui",
    "localminutes.ui.main_window",
    "localminutes.ui.studio_widgets",
    "localminutes.ui.theme",
    "localminutes.ui.widgets",
    "localminutes.ui.widgets.level_meter",
    "localminutes.ui.widgets.settings_dialog",
    "localminutes.ui.widgets.settings_view",
    "localminutes.ui.widgets.sidebar",
    "localminutes.ui.widgets.summary_panel",
    "localminutes.ui.widgets.tasks_hub",
    "localminutes.ui.widgets.transcript_view",
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "sounddevice",
    "scipy.signal",
    "httpx",
    "certifi",
]


def read_project_version(base_dir: Path) -> str:
    pyproject = base_dir / "pyproject.toml"
    if pyproject.is_file():
        m = re.search(
            r'^version\s*=\s*"([^"]+)"',
            pyproject.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if m:
            return m.group(1).strip()
    return DEFAULT_VERSION


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_onedir(base_dir: Path) -> Path:
    print(f"[1/3] Building PyInstaller --onedir bundle '{APP_NAME}'...")
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--collect-all",
        "faster_whisper",
        "--collect-all",
        "ctranslate2",
        "--collect-all",
        "onnxruntime",
        "--collect-all",
        "sounddevice",
        "--collect-all",
        "certifi",
        "--collect-submodules",
        "localminutes",
    ]

    if sys.platform == "win32":
        cmd.extend(["--hidden-import", "pyaudiowpatch"])

    for mod in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", mod])

    ico_path = base_dir / "assets" / "app_icon.ico"
    if ico_path.is_file():
        cmd.extend(["--icon", str(ico_path)])

    assets_dir = base_dir / "assets"
    if assets_dir.is_dir():
        cmd.extend(["--add-data", f"{assets_dir}{sep}assets"])

    cmd.append(str(base_dir / "main.py"))

    env = os.environ.copy()
    pyi_cache = base_dir / "build" / "pyinstaller_cache"
    pyi_cache.mkdir(parents=True, exist_ok=True)
    env["PYINSTALLER_CONFIG_DIR"] = str(pyi_cache)

    subprocess.run(cmd, cwd=str(base_dir), env=env, check=True)
    bundle_dir = base_dir / "dist" / APP_NAME
    if not bundle_dir.is_dir():
        raise RuntimeError(f"Expected PyInstaller bundle not found: {bundle_dir}")
    print(f"[OK] Standalone bundle ready: {bundle_dir}")
    return bundle_dir


def create_portable_zip(base_dir: Path, bundle_dir: Path, version: str) -> Path:
    zip_name = f"{APP_NAME}-Portable-v{version}-Windows-x64.zip"
    zip_path = base_dir / "dist" / zip_name
    if zip_path.exists():
        zip_path.unlink()

    print(f"[2/3] Packaging Portable ZIP: {zip_name} ...")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file_path in sorted(bundle_dir.rglob("*")):
            if file_path.is_file():
                rel = file_path.relative_to(bundle_dir)
                zf.write(file_path, arcname=str(rel))

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[OK] Portable ZIP ready: {zip_path} ({size_mb:.1f} MB)")
    return zip_path


def write_checksums(base_dir: Path, artifacts: list[Path]) -> Path:
    sums_path = base_dir / "dist" / "SHA256SUMS-Windows.txt"
    lines = []
    for art in artifacts:
        digest = sha256_file(art)
        lines.append(f"{digest}  {art.name}\n")
        print(f"[OK] SHA-256 ({art.name}): {digest}")
    sums_path.write_text("".join(lines), encoding="ascii")
    return sums_path


def main() -> int:
    base_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Build LocalMinutes Windows standalone bundle & portable ZIP"
    )
    parser.add_argument("--version", default=read_project_version(base_dir))
    parser.add_argument("--skip-zip", action="store_true")
    args = parser.parse_args()
    version = args.version.lstrip("v")

    bundle_dir = build_onedir(base_dir)
    artifacts: list[Path] = []
    if not args.skip_zip:
        artifacts.append(create_portable_zip(base_dir, bundle_dir, version))
    if artifacts:
        write_checksums(base_dir, artifacts)
    else:
        print("[3/3] Skipped Portable ZIP (--skip-zip).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
