"""Application configuration and OS-native local storage paths."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from localminutes.hardware import get_writable_data_dir
from localminutes.models import AppSettings


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


def load_settings() -> AppSettings:
    """Load settings from JSON, falling back to defaults for missing or invalid fields."""
    path = get_config_path()
    if not path.exists():
        return AppSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return AppSettings()
        defaults = asdict(AppSettings())
        merged = {k: raw.get(k, v) for k, v in defaults.items()}
        return AppSettings(**merged)
    except Exception:
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    """Persist settings to JSON atomically."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)
