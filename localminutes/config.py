"""Application configuration and local storage paths."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from localminutes.models import AppSettings


def get_data_dir() -> Path:
    """Return the persistent local data directory for LocalMinutes."""
    override = os.environ.get("LOCALMINUTES_DATA_DIR")
    if override:
        base = Path(override)
    else:
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata) / "LocalMinutes"
        else:
            base = Path.home() / ".localminutes"
    base.mkdir(parents=True, exist_ok=True)
    return base


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


def load_settings() -> AppSettings:
    """Load settings from JSON, falling back to defaults for missing fields."""
    path = get_config_path()
    if not path.exists():
        return AppSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        defaults = asdict(AppSettings())
        merged = {k: raw.get(k, v) for k, v in defaults.items()}
        return AppSettings(**merged)
    except Exception:
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    """Persist settings to JSON."""
    path = get_config_path()
    path.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
