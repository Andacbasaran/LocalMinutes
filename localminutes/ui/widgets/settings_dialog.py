"""Backwards-compatible modal wrapper around Studio 2.0 SettingsView."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

from localminutes.hardware import compute_runtime_tuning, detect_hardware_profile
from localminutes.i18n import LanguageManager
from localminutes.models import AppSettings
from localminutes.ui.widgets.settings_view import SettingsView


class SettingsDialog(QDialog):
    """Thin modal dialog wrapper around SettingsView for backwards compatibility."""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LocalMinutes — Settings")
        self.resize(780, 620)
        hw = detect_hardware_profile(query_ct2=False)
        tuning = compute_runtime_tuning(hw)
        i18n = LanguageManager(settings.ui_language)
        self._result = settings

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._view = SettingsView(settings, hw, tuning, i18n, parent=self)
        self._view.settings_saved.connect(self._on_saved)
        lay.addWidget(self._view)

    def _on_saved(self, new_settings: AppSettings) -> None:
        self._result = new_settings
        self.accept()

    def get_settings(self) -> AppSettings:
        return self._result
