"""Dual-channel real-time audio level meter widget (Mic + System)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget


class DualLevelMeter(QWidget):
    """Displays live RMS level bars for Microphone ('Sen') and Loopback ('Karşı Taraf')."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mic_val = 0.0
        self._sys_val = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._mic_bar = self._build_row(layout, "Sen (Mik)", "#10b981")
        self._sys_bar = self._build_row(layout, "Karşı Taraf", "#3b82f6")

    def _build_row(self, parent_layout: QVBoxLayout, label_text: str, color: str) -> QProgressBar:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        lbl = QLabel(label_text)
        lbl.setFixedWidth(72)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet("color: #9fb0c8; font-size: 11px;")

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedWidth(110)
        bar.setFixedHeight(8)
        bar.setStyleSheet(
            f"QProgressBar {{ background-color: #121620; border: 1px solid #262c3a; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background-color: {color}; border-radius: 3px; }}"
        )

        row.addWidget(lbl)
        row.addWidget(bar)
        parent_layout.addLayout(row)
        return bar

    def set_level(self, speaker: str, level: float) -> None:
        clamped = max(0.0, min(1.0, level))
        if speaker == "Sen":
            self._mic_val = max(clamped, self._mic_val * 0.72)
            self._mic_bar.setValue(int(self._mic_val * 100))
        else:
            self._sys_val = max(clamped, self._sys_val * 0.72)
            self._sys_bar.setValue(int(self._sys_val * 100))

    def reset(self) -> None:
        self._mic_val = 0.0
        self._sys_val = 0.0
        self._mic_bar.setValue(0)
        self._sys_bar.setValue(0)
