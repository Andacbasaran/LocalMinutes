"""Meeting archive sidebar with instant full-text search."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from localminutes.export.exporter import format_timestamp
from localminutes.models import Meeting


class ArchiveSidebar(QWidget):
    """Left sidebar listing past meetings with instant FTS search."""

    meeting_selected = pyqtSignal(int)
    new_meeting_requested = pyqtSignal()
    delete_meeting_requested = pyqtSignal(int)
    search_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(230)
        self.setMaximumWidth(340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Toplantı Arşivi")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch()

        self._new_btn = QPushButton("+ Yeni")
        self._new_btn.setObjectName("PrimaryButton")
        self._new_btn.setToolTip("Yeni boş toplantı oturumu oluştur")
        self._new_btn.clicked.connect(self.new_meeting_requested.emit)
        header.addWidget(self._new_btn)
        layout.addLayout(header)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Arşivde ve transkriptlerde ara...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self.search_changed.emit)
        layout.addWidget(self._search_input)

        self._list = QListWidget()
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._open_context_menu)
        self._list.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self._list, 1)

        self._count_label = QLabel("0 kayıt")
        self._count_label.setObjectName("MutedLabel")
        layout.addWidget(self._count_label)

    def set_meetings(self, meetings: list[Meeting], selected_id: int | None = None) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        selected_row = -1
        for idx, m in enumerate(meetings):
            date_str = m.created_at.replace("T", " ")[:16]
            dur_str = format_timestamp(m.duration_sec)
            summary_badge = "  ✦" if m.summary else ""
            item = QListWidgetItem(f"{m.title}{summary_badge}\n{date_str}  •  {dur_str}")
            item.setData(Qt.ItemDataRole.UserRole, m.id)
            self._list.addItem(item)
            if selected_id is not None and m.id == selected_id:
                selected_row = idx
        if selected_row >= 0:
            self._list.setCurrentRow(selected_row)
        self._list.blockSignals(False)
        self._count_label.setText(f"{len(meetings)} kayıt")

    def _on_current_changed(self, current: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if current is None:
            return
        meeting_id = current.data(Qt.ItemDataRole.UserRole)
        if meeting_id is not None:
            self.meeting_selected.emit(int(meeting_id))

    def _open_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        meeting_id = item.data(Qt.ItemDataRole.UserRole)
        if meeting_id is None:
            return
        menu = QMenu(self)
        delete_action = menu.addAction("Toplantıyı Sil")
        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen == delete_action:
            self.delete_meeting_requested.emit(int(meeting_id))
