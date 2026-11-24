#!/usr/bin/env python3
"""LocalMinutes — Linux Portable .tar.gz, AppDir & optional AppImage Build Tool.

Usage:
    python scripts/build_linux.py
    python scripts/build_linux.py --version 1.0.0 --arch x86_64 --skip-appimage
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

APP_NAME = "LocalMinutes"
DESKTOP_ID = "com.andacbasaran.LocalMinutes.desktop"
ICON_NAME = "localminutes"
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


def build_onedir_bundle(base_dir: Path) -> Path:
    print(f"[1/4] Building PyInstaller --onedir bundle '{APP_NAME}'...")
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
    for mod in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", mod])

    assets_dir = base_dir / "assets"
    if assets_dir.is_dir():
        cmd.extend(["--add-data", f"{assets_dir}:assets"])

    cmd.append(str(base_dir / "main.py"))

    env = os.environ.copy()
    pyi_cache = base_dir / "build" / "pyinstaller_cache"
    pyi_cache.mkdir(parents=True, exist_ok=True)
    env["PYINSTALLER_CONFIG_DIR"] = str(pyi_cache)

    subprocess.run(cmd, cwd=str(base_dir), env=env, check=True)
    bundle_dir = base_dir / "dist" / APP_NAME
    if not bundle_dir.is_dir():
        raise RuntimeError(f"Expected PyInstaller bundle not found: {bundle_dir}")
    return bundle_dir


def create_tarball(base_dir: Path, bundle_dir: Path, version: str, arch: str) -> Path:
    tar_name = f"{APP_NAME}-v{version}-Linux-{arch}.tar.gz"
    tar_path = base_dir / "dist" / tar_name
    if tar_path.exists():
        tar_path.unlink()

    print(f"[2/4] Packaging portable archive: {tar_name} ...")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(bundle_dir, arcname=APP_NAME)
    size_mb = tar_path.stat().st_size / (1024 * 1024)
    print(f"[OK] Portable archive ready: {tar_path} ({size_mb:.1f} MB)")
    return tar_path


def assemble_appdir(base_dir: Path, bundle_dir: Path) -> Path:
    print(f"[3/4] Assembling dist/{APP_NAME}.AppDir ...")
    appdir = base_dir / "dist" / f"{APP_NAME}.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)

    usr_bin = appdir / "usr" / "bin"
    usr_apps = appdir / "usr" / "share" / "applications"
    usr_icons = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    usr_apps.mkdir(parents=True, exist_ok=True)
    usr_icons.mkdir(parents=True, exist_ok=True)

    shutil.copytree(bundle_dir, usr_bin, symlinks=True)

    apprun_src = base_dir / "packaging" / "linux" / "AppRun"
    apprun_dst = appdir / "AppRun"
    shutil.copy2(apprun_src, apprun_dst)
    os.chmod(apprun_dst, os.stat(apprun_dst).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    desktop_src = base_dir / "packaging" / "linux" / DESKTOP_ID
    shutil.copy2(desktop_src, appdir / DESKTOP_ID)
    shutil.copy2(desktop_src, usr_apps / DESKTOP_ID)

    icon_src = base_dir / "assets" / "app_icon.png"
    if icon_src.is_file():
        shutil.copy2(icon_src, appdir / f"{ICON_NAME}.png")
        shutil.copy2(icon_src, appdir / ".DirIcon")
        shutil.copy2(icon_src, usr_icons / f"{ICON_NAME}.png")

    print(f"[OK] AppDir assembled: {appdir}")
    return appdir


def build_appimage(base_dir: Path, appdir: Path, version: str, arch: str) -> Path | None:
    tool = shutil.which("appimagetool")
    if not tool:
        print("[INFO] 'appimagetool' not found on PATH; skipping AppImage generation.")
        return None
    appimage_name = f"{APP_NAME}-v{version}-Linux-{arch}.AppImage"
    appimage_path = base_dir / "dist" / appimage_name
    if appimage_path.exists():
        appimage_path.unlink()

    print(f"[4/4] Building AppImage: {appimage_name} ...")
    env = os.environ.copy()
    env["ARCH"] = arch
    subprocess.run([tool, str(appdir), str(appimage_path)], cwd=str(base_dir), env=env, check=True)
    return appimage_path


def write_checksums(base_dir: Path, artifacts: list[Path]) -> Path:
    sums_path = base_dir / "dist" / "SHA256SUMS-Linux.txt"
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
        description="Build LocalMinutes Linux portable .tar.gz and AppImage"
    )
    parser.add_argument("--version", default=read_project_version(base_dir))
    parser.add_argument("--arch", default="x86_64", choices=["x86_64", "aarch64"])
    parser.add_argument("--skip-appimage", action="store_true")
    args = parser.parse_args()
    version = args.version.lstrip("v")

    if not sys.platform.startswith("linux"):
        print("[ERROR] build_linux.py must be run on Linux.")
        return 1

    bundle_dir = build_onedir_bundle(base_dir)
    artifacts = [create_tarball(base_dir, bundle_dir, version, args.arch)]
    appdir = assemble_appdir(base_dir, bundle_dir)
    if not args.skip_appimage:
        img = build_appimage(base_dir, appdir, version, args.arch)
        if img is not None:
            artifacts.append(img)
    else:
        print("[4/4] Skipping AppImage packaging (--skip-appimage).")
    write_checksums(base_dir, artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
