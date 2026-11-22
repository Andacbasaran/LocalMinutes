"""Interactive speaker-labeled transcript viewer with search, filters, bookmarks, and editing."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from localminutes.analytics import compute_meeting_stats
from localminutes.export.exporter import format_timestamp
from localminutes.models import TranscriptSegment


class _SegmentEditDialog(QDialog):
    """Inline editor dialog for correcting a transcript segment's speaker or text."""

    def __init__(self, segment: TranscriptSegment, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Transkript Satırını Düzenle")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._speaker_combo = QComboBox()
        self._speaker_combo.setEditable(True)
        for spk in ["Sen", "Karşı Taraf", "Kayıt"]:
            self._speaker_combo.addItem(spk)
        self._speaker_combo.setCurrentText(segment.speaker)
        form.addRow("Konuşmacı:", self._speaker_combo)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlainText(segment.text)
        self._text_edit.setMinimumHeight(100)
        form.addRow("Metin:", self._text_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Kaydet")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> tuple[str, str]:
        return self._speaker_combo.currentText().strip() or "Sen", self._text_edit.toPlainText().strip()


class _SegmentCard(QFrame):
    """Visual card for a single transcript segment inside the list."""

    bookmark_toggled = pyqtSignal(int, bool)
    edit_clicked = pyqtSignal(int)

    def __init__(self, segment: TranscriptSegment, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segment = segment
        is_user = segment.speaker == "Sen"
        border_color = "#10b981" if is_user else ("#a855f7" if segment.speaker == "Kayıt" else "#3b82f6")
        badge_bg = "#12382c" if is_user else ("#2e1a47" if segment.speaker == "Kayıt" else "#172a4a")
        badge_fg = "#34d399" if is_user else ("#c084fc" if segment.speaker == "Kayıt" else "#60a5fa")
        bg_color = "#1d2230" if segment.is_bookmarked else "#161b26"

        self.setStyleSheet(
            f"QFrame {{ background-color: {bg_color}; border: 1px solid #242b3a; "
            f"border-left: 3px solid {border_color}; border-radius: 7px; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 7, 10, 7)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        badge = QLabel(segment.speaker)
        badge.setStyleSheet(
            f"background-color: {badge_bg}; color: {badge_fg}; font-weight: 700; "
            f"font-size: 11px; padding: 2px 7px; border-radius: 4px; border: none;"
        )
        top.addWidget(badge)

        ts_lbl = QLabel(format_timestamp(segment.start_sec))
        ts_lbl.setStyleSheet("color: #7d8590; font-size: 11px; border: none; background: transparent;")
        top.addWidget(ts_lbl)
        top.addStretch()

        star_btn = QToolButton()
        star_btn.setText("★" if segment.is_bookmarked else "☆")
        star_btn.setToolTip("Önemli an olarak işaretle")
        star_color = "#fbbf24" if segment.is_bookmarked else "#6b7280"
        star_btn.setStyleSheet(
            f"QToolButton {{ color: {star_color}; background: transparent; border: none; font-size: 15px; }}"
            "QToolButton:hover { color: #fde047; }"
        )
        if segment.id is not None:
            star_btn.clicked.connect(
                lambda _c=False, sid=segment.id, bm=not segment.is_bookmarked: self.bookmark_toggled.emit(sid, bm)
            )
        top.addWidget(star_btn)

        edit_btn = QToolButton()
        edit_btn.setText("✎")
        edit_btn.setToolTip("Metni veya konuşmacıyı düzenle")
        edit_btn.setStyleSheet(
            "QToolButton { color: #7d8590; background: transparent; border: none; font-size: 13px; }"
            "QToolButton:hover { color: #e6edf3; }"
        )
        if segment.id is not None:
            edit_btn.clicked.connect(lambda _c=False, sid=segment.id: self.edit_clicked.emit(sid))
        top.addWidget(edit_btn)

        root.addLayout(top)

        text_lbl = QLabel(segment.text.strip())
        text_lbl.setWordWrap(True)
        text_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_lbl.setStyleSheet(
            "color: #e6edf3; font-size: 13px; line-height: 1.4; border: none; background: transparent;"
        )
        root.addWidget(text_lbl)


class TranscriptView(QWidget):
    """Displays interactive speaker-labeled transcript cards with filters, search, and stats."""

    segment_updated = pyqtSignal(int, str, str)  # segment_id, speaker, text
    segment_bookmarked = pyqtSignal(int, bool)  # segment_id, is_bookmarked
    segment_deleted = pyqtSignal(int)  # segment_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: list[TranscriptSegment] = []
        self._filter_query: str = ""
        self._active_filter: str = "all"  # "all" | "Sen" | "Karşı Taraf" | "bookmarked"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("Canlı Transkript")
        title.setObjectName("SectionTitle")
        header.addWidget(title)

        self._count_label = QLabel("0 satır")
        self._count_label.setObjectName("MutedLabel")
        header.addWidget(self._count_label)
        header.addStretch()

        self._bookmark_last_btn = QPushButton("★ Anı İşaretle")
        self._bookmark_last_btn.setObjectName("ExportButton")
        self._bookmark_last_btn.setToolTip("Son konuşma satırını önemli an olarak işaretle (Ctrl+B)")
        self._bookmark_last_btn.clicked.connect(self.bookmark_latest)
        header.addWidget(self._bookmark_last_btn)

        self._auto_scroll_cb = QCheckBox("Otomatik kaydır")
        self._auto_scroll_cb.setChecked(True)
        header.addWidget(self._auto_scroll_cb)
        layout.addLayout(header)

        # Search + Filter row
        controls = QHBoxLayout()
        controls.setSpacing(6)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Transkript içinde ara (Ctrl+F)...")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._on_filter_changed)
        controls.addWidget(self._search_box, 1)

        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        for key, label in [
            ("all", "Tümü"),
            ("Sen", "Sen"),
            ("Karşı Taraf", "Karşı Taraf"),
            ("bookmarked", "★ İşaretliler"),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setObjectName("ExportButton")
            if key == "all":
                btn.setChecked(True)
            btn.clicked.connect(lambda _c=False, k=key: self._set_filter_mode(k))
            self._filter_group.addButton(btn)
            controls.addWidget(btn)

        layout.addLayout(controls)

        # Stats bar
        self._stats_label = QLabel("Henüz konuşma verisi yok.")
        self._stats_label.setObjectName("MutedLabel")
        layout.addWidget(self._stats_label)

        # Segment list
        self._list = QListWidget()
        self._list.setSpacing(5)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._open_context_menu)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list, 1)

    def focus_search(self) -> None:
        self._search_box.setFocus()
        self._search_box.selectAll()

    def set_segments(self, segments: list[TranscriptSegment]) -> None:
        self._segments = list(segments)
        self._render()

    def append_segment(self, segment: TranscriptSegment) -> None:
        self._segments.append(segment)
        self._update_stats()
        if self._matches_filter(segment):
            self._add_card_item(segment)
            if self._auto_scroll_cb.isChecked():
                self._list.scrollToBottom()
        self._update_count_label()

    def clear(self) -> None:
        self._segments.clear()
        self._list.clear()
        self._count_label.setText("0 satır")
        self._stats_label.setText("Henüz konuşma verisi yok.")

    def bookmark_latest(self) -> None:
        if not self._segments:
            return
        last = self._segments[-1]
        if last.id is not None:
            new_state = not last.is_bookmarked
            self.segment_bookmarked.emit(last.id, new_state)

    def update_segment_local(
        self,
        segment_id: int,
        speaker: Optional[str] = None,
        text: Optional[str] = None,
        is_bookmarked: Optional[bool] = None,
    ) -> None:
        for seg in self._segments:
            if seg.id == segment_id:
                if speaker is not None:
                    seg.speaker = speaker
                if text is not None:
                    seg.text = text
                if is_bookmarked is not None:
                    seg.is_bookmarked = is_bookmarked
                break
        self._render()

    def remove_segment_local(self, segment_id: int) -> None:
        self._segments = [s for s in self._segments if s.id != segment_id]
        self._render()

    def _set_filter_mode(self, mode: str) -> None:
        self._active_filter = mode
        self._render()

    def _on_filter_changed(self, text: str) -> None:
        self._filter_query = text.strip().lower()
        self._render()

    def _matches_filter(self, seg: TranscriptSegment) -> bool:
        if self._active_filter == "bookmarked" and not seg.is_bookmarked:
            return False
        if self._active_filter in ("Sen", "Karşı Taraf") and seg.speaker != self._active_filter:
            return False
        if self._filter_query:
            haystack = f"{seg.speaker} {seg.text}".lower()
            if self._filter_query not in haystack:
                return False
        return True

    def _render(self) -> None:
        self._list.clear()
        for seg in self._segments:
            if self._matches_filter(seg):
                self._add_card_item(seg)
        self._update_stats()
        self._update_count_label()

    def _add_card_item(self, seg: TranscriptSegment) -> None:
        card = _SegmentCard(seg)
        card.bookmark_toggled.connect(self.segment_bookmarked.emit)
        card.edit_clicked.connect(self._open_edit_dialog_by_id)

        item = QListWidgetItem(self._list)
        item.setData(Qt.ItemDataRole.UserRole, seg.id)
        item.setSizeHint(card.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, card)

    def _update_count_label(self) -> None:
        visible = self._list.count()
        total = len(self._segments)
        if visible != total:
            self._count_label.setText(f"{visible} / {total} satır")
        else:
            self._count_label.setText(f"{total} satır")

    def _update_stats(self) -> None:
        stats = compute_meeting_stats(self._segments)
        if stats.total_segments == 0:
            self._stats_label.setText("Henüz konuşma verisi yok.")
            return
        parts = [f"{stats.total_words} kelime"]
        if stats.bookmarked_count:
            parts.append(f"★ {stats.bookmarked_count} işaretli")
        if stats.speaker_word_share:
            share_str = " / ".join(f"{spk} %{pct:.0f}" for spk, pct in stats.speaker_word_share.items())
            parts.append(share_str)
        self._stats_label.setText("  •  ".join(parts))

    def _find_segment(self, seg_id: int) -> Optional[TranscriptSegment]:
        for seg in self._segments:
            if seg.id == seg_id:
                return seg
        return None

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        seg_id = item.data(Qt.ItemDataRole.UserRole)
        if seg_id is not None:
            self._open_edit_dialog_by_id(int(seg_id))

    def _open_edit_dialog_by_id(self, seg_id: int) -> None:
        seg = self._find_segment(seg_id)
        if seg is None:
            return
        dlg = _SegmentEditDialog(seg, parent=self)
        if dlg.exec():
            new_speaker, new_text = dlg.get_values()
            if new_text:
                self.segment_updated.emit(seg_id, new_speaker, new_text)

    def _open_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        seg_id = item.data(Qt.ItemDataRole.UserRole)
        if seg_id is None:
            return
        seg = self._find_segment(int(seg_id))
        if seg is None:
            return

        menu = QMenu(self)
        bm_label = "★ İşareti Kaldır" if seg.is_bookmarked else "☆ Önemli An Olarak İşaretle"
        bm_act = menu.addAction(bm_label)
        edit_act = menu.addAction("✎ Düzenle")
        del_act = menu.addAction("🗑 Satırı Sil")

        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen == bm_act:
            self.segment_bookmarked.emit(int(seg_id), not seg.is_bookmarked)
        elif chosen == edit_act:
            self._open_edit_dialog_by_id(int(seg_id))
        elif chosen == del_act:
            self.segment_deleted.emit(int(seg_id))
