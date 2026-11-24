"""Studio 2.0 Interactive Transcript Stream — amber search highlights, dynamic speaker pills & bulk rename."""

from __future__ import annotations

import html
import re
from typing import Optional

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QTextDocument
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
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
from localminutes.i18n import LanguageManager
from localminutes.models import TranscriptSegment
from localminutes.ui.studio_widgets import FlatSwitch, make_flat_icon

_SPEAKER_PALETTE = [
    ("#10B981", "rgba(16, 185, 129, 0.16)", "#34D399"),  # Emerald Mint (You/Sen)
    ("#38BDF8", "rgba(56, 189, 248, 0.16)", "#7DD3FC"),  # Sky (Remote)
    ("#A78BFA", "rgba(167, 139, 250, 0.16)", "#C4B5FD"),  # Violet
    ("#F59E0B", "rgba(245, 158, 11, 0.16)", "#FCD34D"),  # Amber
    ("#FB7185", "rgba(251, 113, 133, 0.16)", "#FDA4AF"),  # Rose
]


def speaker_color_tokens(speaker: str) -> tuple[str, str, str]:
    """Return `(accent_hex, badge_bg, badge_fg)` consistently for any speaker label."""
    low = speaker.strip().lower()
    if low in ("you", "sen", "me"):
        return _SPEAKER_PALETTE[0]
    if low in ("remote", "karşı taraf"):
        return _SPEAKER_PALETTE[1]
    if low in ("recording", "kayıt"):
        return _SPEAKER_PALETTE[2]
    idx = (sum(ord(c) for c in low) % (len(_SPEAKER_PALETTE) - 1)) + 1
    return _SPEAKER_PALETTE[idx]


class _TalkRatioBar(QWidget):
    """Slim visual speaker talk-ratio bar rendered directly above the transcript stream."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shares: list[tuple[str, float, str]] = []
        self.setFixedHeight(5)

    def set_shares(self, speaker_shares: dict[str, float]) -> None:
        self._shares = [
            (spk, pct, speaker_color_tokens(spk)[0])
            for spk, pct in speaker_shares.items()
            if pct > 0
        ]
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#1B1B21"))
            p.drawRoundedRect(0, 0, w, h, 2, 2)
            if not self._shares:
                return
            total = sum(pct for _, pct, _ in self._shares) or 100.0
            x = 0.0
            for _spk, pct, hex_col in self._shares:
                seg_w = max(4.0, (pct / total) * w)
                p.setBrush(QColor(hex_col))
                p.drawRoundedRect(int(x), 0, int(seg_w) - 1, h, 2, 2)
                x += seg_w
        finally:
            p.end()


class _SegmentEditDialog(QDialog):
    """Inline editor dialog for correcting a transcript segment's speaker or text."""

    def __init__(
        self,
        segment: TranscriptSegment,
        known_speakers: list[str],
        i18n: LanguageManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.t("dlg_edit_title"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self._speaker_combo = QComboBox()
        self._speaker_combo.setEditable(True)
        choices = list(dict.fromkeys([segment.speaker, *known_speakers, "You", "Remote", "Recording"]))
        for spk in choices:
            if spk.strip():
                self._speaker_combo.addItem(spk)
        self._speaker_combo.setCurrentText(segment.speaker)
        form.addRow(i18n.t("dlg_speaker"), self._speaker_combo)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlainText(segment.text)
        self._text_edit.setMinimumHeight(105)
        form.addRow(i18n.t("dlg_text"), self._text_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.t("dlg_save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("dlg_cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> tuple[str, str]:
        return self._speaker_combo.currentText().strip() or "You", self._text_edit.toPlainText().strip()


class _SegmentCard(QFrame):
    """Studio 2.0 transcript segment card with amber match highlight & accurate non-clipping sizing."""

    bookmark_toggled = pyqtSignal(int, bool)
    edit_clicked = pyqtSignal(int)
    delete_clicked = pyqtSignal(int)

    def __init__(
        self,
        segment: TranscriptSegment,
        highlight_query: str = "",
        highlighted_flash: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._segment = segment
        accent_hex, badge_bg, badge_fg = speaker_color_tokens(segment.speaker)

        if highlighted_flash:
            bg_color = "#132920"
            border_all = "#10B981"
        elif segment.is_bookmarked:
            bg_color = "#181B20"
            border_all = "#343440"
        else:
            bg_color = "#141417"
            border_all = "#24242A"

        self.setObjectName("SegmentCard")
        self.setStyleSheet(
            f"QFrame#SegmentCard {{ background-color: {bg_color}; border: 1px solid {border_all}; "
            f"border-left: 3px solid {accent_hex}; border-radius: 8px; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(11, 8, 11, 9)
        root.setSpacing(5)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(7)

        badge = QLabel(segment.speaker)
        badge.setStyleSheet(
            f"background-color: {badge_bg}; color: {badge_fg}; font-weight: 700; "
            f"font-size: 11px; padding: 2px 8px; border-radius: 5px; border: none;"
        )
        top.addWidget(badge)

        ts_lbl = QLabel(format_timestamp(segment.start_sec))
        ts_lbl.setStyleSheet("color: #71717A; font-size: 11px; font-weight: 600; border: none;")
        top.addWidget(ts_lbl)
        top.addStretch()

        star_btn = QToolButton()
        star_icon = make_flat_icon(
            "star_filled" if segment.is_bookmarked else "star",
            "#F59E0B" if segment.is_bookmarked else "#71717A",
            13,
        )
        star_btn.setIcon(star_icon)
        star_btn.setIconSize(QSize(13, 13))
        star_btn.setStyleSheet("QToolButton { background: transparent; border: none; padding: 2px; }")
        star_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if segment.id is not None:
            star_btn.clicked.connect(
                lambda _c=False, sid=segment.id, bm=not segment.is_bookmarked: self.bookmark_toggled.emit(sid, bm)
            )
        top.addWidget(star_btn)

        edit_btn = QToolButton()
        edit_btn.setIcon(make_flat_icon("edit", "#71717A", 12))
        edit_btn.setIconSize(QSize(12, 12))
        edit_btn.setStyleSheet("QToolButton { background: transparent; border: none; padding: 2px; }")
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if segment.id is not None:
            edit_btn.clicked.connect(lambda _c=False, sid=segment.id: self.edit_clicked.emit(sid))
        top.addWidget(edit_btn)

        del_btn = QToolButton()
        del_btn.setIcon(make_flat_icon("trash", "#71717A", 12))
        del_btn.setIconSize(QSize(12, 12))
        del_btn.setStyleSheet("QToolButton { background: transparent; border: none; padding: 2px; }")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if segment.id is not None:
            del_btn.clicked.connect(lambda _c=False, sid=segment.id: self.delete_clicked.emit(sid))
        top.addWidget(del_btn)

        root.addLayout(top)

        self._text_lbl = QLabel()
        self._text_lbl.setWordWrap(True)
        self._text_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._text_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._text_lbl.setStyleSheet(
            "color: #E4E4E7; font-size: 12.5px; border: none; background: transparent;"
        )
        self._text_lbl.setText(self._render_highlighted_html(segment.text.strip(), highlight_query))
        root.addWidget(self._text_lbl)

    @staticmethod
    def _render_highlighted_html(text: str, query: str) -> str:
        escaped = html.escape(text)
        if not query:
            return f"<div style='line-height:1.42;'>{escaped}</div>"
        pattern = re.compile(re.escape(html.escape(query)), re.IGNORECASE)
        highlighted = pattern.sub(
            lambda m: (
                "<span style='background-color:rgba(245,158,11,0.34); color:#FDE68A; "
                f"border-radius:3px; padding:0 2px;'>{m.group(0)}</span>"
            ),
            escaped,
        )
        return f"<div style='line-height:1.42;'>{highlighted}</div>"

    def compute_height_for_width(self, card_width: int) -> int:
        """Compute exact vertical size so multi-line text never clips in QListWidget."""
        usable_text_w = max(180, card_width - 28)
        doc = QTextDocument()
        doc.setDefaultFont(self._text_lbl.font())
        doc.setHtml(self._text_lbl.text())
        doc.setTextWidth(float(usable_text_w))
        text_h = int(doc.size().height()) + 6
        return max(64, 40 + text_h)


class TranscriptView(QWidget):
    """Studio 2.0 interactive transcript viewer with dynamic speaker filters, bulk rename & citation jump."""

    segment_updated = pyqtSignal(int, str, str)  # segment_id, speaker, text
    segment_bookmarked = pyqtSignal(int, bool)  # segment_id, is_bookmarked
    segment_deleted = pyqtSignal(int)  # segment_id
    speaker_bulk_renamed = pyqtSignal(str, str)  # old_speaker, new_speaker

    def __init__(self, i18n: LanguageManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._i18n = i18n
        self._segments: list[TranscriptSegment] = []
        self._filter_query: str = ""
        self._active_filter: str = "all"  # "all" | "bookmarked" | <speaker_name>
        self._flash_segment_id: Optional[int] = None
        self._filter_buttons: list[QPushButton] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 8, 10)
        layout.setSpacing(8)

        # --- Header Row ---
        header = QHBoxLayout()
        header.setSpacing(8)
        self._title_lbl = QLabel(i18n.t("transcript_title"))
        self._title_lbl.setObjectName("SectionTitle")
        header.addWidget(self._title_lbl)

        self._count_label = QLabel(i18n.t("transcript_lines_count", count=0))
        self._count_label.setStyleSheet(
            "color: #A1A1AA; background-color: #141417; border: 1px solid #24242A; "
            "border-radius: 10px; padding: 2px 8px; font-size: 11px; font-weight: 600;"
        )
        header.addWidget(self._count_label)
        header.addStretch()

        self._bookmark_last_btn = QPushButton(i18n.t("transcript_bookmark_last"))
        self._bookmark_last_btn.setObjectName("GhostButton")
        self._bookmark_last_btn.setIcon(make_flat_icon("star", "#F59E0B", 12))
        self._bookmark_last_btn.setIconSize(QSize(12, 12))
        self._bookmark_last_btn.setToolTip("Bookmark latest segment (Ctrl+B)")
        self._bookmark_last_btn.clicked.connect(self.bookmark_latest)
        header.addWidget(self._bookmark_last_btn)

        self._rename_btn = QPushButton(i18n.t("transcript_rename_speaker"))
        self._rename_btn.setObjectName("GhostButton")
        self._rename_btn.setIcon(make_flat_icon("rename", "#A1A1AA", 12))
        self._rename_btn.setIconSize(QSize(12, 12))
        self._rename_btn.clicked.connect(self._open_bulk_rename_picker)
        header.addWidget(self._rename_btn)

        self._auto_scroll_cb = FlatSwitch(i18n.t("transcript_autoscroll"))
        self._auto_scroll_cb.setChecked(True)
        header.addWidget(self._auto_scroll_cb)
        layout.addLayout(header)

        # --- Search + Dynamic Filter Pills ---
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(i18n.t("transcript_search_ph"))
        self._search_box.setClearButtonEnabled(True)
        self._search_box.setFixedHeight(32)
        self._search_box.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._search_box)

        self._pills_layout = QHBoxLayout()
        self._pills_layout.setContentsMargins(0, 0, 0, 0)
        self._pills_layout.setSpacing(6)
        layout.addLayout(self._pills_layout)

        # --- Talk Ratio Bar & Stats ---
        self._talk_bar = _TalkRatioBar()
        layout.addWidget(self._talk_bar)

        self._stats_label = QLabel(i18n.t("transcript_empty_stats"))
        self._stats_label.setObjectName("MutedLabel")
        layout.addWidget(self._stats_label)

        # --- Segment List ---
        self._list = QListWidget()
        self._list.setObjectName("TranscriptList")
        self._list.setSpacing(4)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._open_context_menu)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list, 1)

        self._rebuild_filter_pills()

    def retranslate(self, i18n: LanguageManager) -> None:
        self._i18n = i18n
        self._title_lbl.setText(i18n.t("transcript_title"))
        self._bookmark_last_btn.setText(i18n.t("transcript_bookmark_last"))
        self._rename_btn.setText(i18n.t("transcript_rename_speaker"))
        self._auto_scroll_cb.setText(i18n.t("transcript_autoscroll"))
        self._search_box.setPlaceholderText(i18n.t("transcript_search_ph"))
        self._rebuild_filter_pills()
        self._update_stats()
        self._update_count_label()

    def focus_search(self) -> None:
        self._search_box.setFocus()
        self._search_box.selectAll()

    def distinct_speakers(self) -> list[str]:
        return list(dict.fromkeys(seg.speaker for seg in self._segments if seg.speaker.strip()))

    def _rebuild_filter_pills(self) -> None:
        while self._pills_layout.count():
            item = self._pills_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._filter_buttons.clear()

        speakers = self.distinct_speakers()
        if self._active_filter not in ("all", "bookmarked") and self._active_filter not in speakers:
            self._active_filter = "all"

        pills: list[tuple[str, str]] = [("all", self._i18n.t("filter_all"))]
        for spk in speakers:
            pills.append((spk, spk))
        pills.append(("bookmarked", self._i18n.t("filter_bookmarked")))

        for key, label in pills:
            btn = QPushButton(label)
            btn.setObjectName("FilterPill")
            btn.setCheckable(True)
            btn.setChecked(self._active_filter == key)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if key == "bookmarked":
                btn.setIcon(make_flat_icon("star_filled", "#F59E0B", 11))
                btn.setIconSize(QSize(11, 11))
            btn.clicked.connect(lambda _c=False, k=key: self._set_filter_mode(k))
            self._filter_buttons.append(btn)
            self._pills_layout.addWidget(btn)
        self._pills_layout.addStretch()

    def set_segments(self, segments: list[TranscriptSegment]) -> None:
        self._segments = list(segments)
        self._rebuild_filter_pills()
        self._render()

    def append_segment(self, segment: TranscriptSegment) -> None:
        prev_speakers = set(self.distinct_speakers())
        self._segments.append(segment)
        if segment.speaker not in prev_speakers:
            self._rebuild_filter_pills()
        self._update_stats()
        if self._matches_filter(segment):
            self._add_card_item(segment)
            if self._auto_scroll_cb.isChecked():
                self._list.scrollToBottom()
        self._update_count_label()

    def clear(self) -> None:
        self._segments.clear()
        self._list.clear()
        self._talk_bar.set_shares({})
        self._rebuild_filter_pills()
        self._count_label.setText(self._i18n.t("transcript_lines_count", count=0))
        self._stats_label.setText(self._i18n.t("transcript_empty_stats"))

    def bookmark_latest(self) -> None:
        if not self._segments:
            return
        last = self._segments[-1]
        if last.id is not None:
            self.segment_bookmarked.emit(last.id, not last.is_bookmarked)

    def scroll_to_citation(self, segment_id: Optional[int], timestamp_sec: float) -> None:
        """Jump straight to a cited transcript segment and highlight it briefly in Emerald Mint."""
        if self._active_filter != "all" or self._filter_query:
            self._active_filter = "all"
            self._filter_query = ""
            self._search_box.blockSignals(True)
            self._search_box.clear()
            self._search_box.blockSignals(False)
            self._rebuild_filter_pills()

        target_id = segment_id
        if target_id is None and self._segments:
            nearest = min(self._segments, key=lambda s: abs(s.start_sec - timestamp_sec))
            target_id = nearest.id

        self._flash_segment_id = target_id
        self._render()

        for row in range(self._list.count()):
            item = self._list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == target_id:
                self._list.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)
                self._list.setCurrentRow(row)
                break

        QTimer.singleShot(1800, self._clear_citation_flash)

    def _clear_citation_flash(self) -> None:
        if self._flash_segment_id is not None:
            self._flash_segment_id = None
            self._render()

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
        self._rebuild_filter_pills()
        self._render()

    def remove_segment_local(self, segment_id: int) -> None:
        self._segments = [s for s in self._segments if s.id != segment_id]
        self._rebuild_filter_pills()
        self._render()

    def _set_filter_mode(self, mode: str) -> None:
        self._active_filter = mode
        self._rebuild_filter_pills()
        self._render()

    def _on_filter_changed(self, text: str) -> None:
        self._filter_query = text.strip().lower()
        self._render()

    def _matches_filter(self, seg: TranscriptSegment) -> bool:
        if self._active_filter == "bookmarked" and not seg.is_bookmarked:
            return False
        if self._active_filter not in ("all", "bookmarked") and seg.speaker != self._active_filter:
            return False
        if self._filter_query:
            haystack = f"{seg.speaker} {seg.text}".lower()
            if self._filter_query not in haystack:
                return False
        return True

    def _card_target_width(self) -> int:
        vp_w = self._list.viewport().width() if self._list.viewport() else 420
        return max(260, vp_w - 18)

    def _render(self) -> None:
        self._list.clear()
        for seg in self._segments:
            if self._matches_filter(seg):
                self._add_card_item(seg)
        self._update_stats()
        self._update_count_label()

    def _add_card_item(self, seg: TranscriptSegment) -> None:
        is_flash = self._flash_segment_id is not None and seg.id == self._flash_segment_id
        card = _SegmentCard(seg, highlight_query=self._filter_query, highlighted_flash=is_flash)
        card.bookmark_toggled.connect(self.segment_bookmarked.emit)
        card.edit_clicked.connect(self._open_edit_dialog_by_id)
        card.delete_clicked.connect(self.segment_deleted.emit)

        w = self._card_target_width()
        h = card.compute_height_for_width(w)
        item = QListWidgetItem(self._list)
        item.setData(Qt.ItemDataRole.UserRole, seg.id)
        item.setSizeHint(QSize(w, h))
        self._list.addItem(item)
        self._list.setItemWidget(item, card)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._recalculate_card_sizes()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._recalculate_card_sizes()

    def _recalculate_card_sizes(self) -> None:
        w = self._card_target_width()
        for row in range(self._list.count()):
            item = self._list.item(row)
            widget = self._list.itemWidget(item) if item else None
            if item is not None and isinstance(widget, _SegmentCard):
                item.setSizeHint(QSize(w, widget.compute_height_for_width(w)))

    def _update_count_label(self) -> None:
        visible = self._list.count()
        total = len(self._segments)
        if visible != total:
            self._count_label.setText(
                self._i18n.t("transcript_lines_filtered", visible=visible, total=total)
            )
        else:
            self._count_label.setText(self._i18n.t("transcript_lines_count", count=total))

    def _update_stats(self) -> None:
        stats = compute_meeting_stats(self._segments)
        self._talk_bar.set_shares(stats.speaker_word_share)
        if stats.total_segments == 0:
            self._stats_label.setText(self._i18n.t("transcript_empty_stats"))
            return
        parts = [self._i18n.t("transcript_words", words=stats.total_words)]
        if stats.words_per_minute > 0:
            parts.append(f"{stats.words_per_minute:.0f} WPM")
        if stats.bookmarked_count:
            parts.append(self._i18n.t("transcript_bookmarked_cnt", count=stats.bookmarked_count))
        if stats.speaker_word_share:
            share_str = " · ".join(f"{spk} {pct:.0f}%" for spk, pct in stats.speaker_word_share.items())
            parts.append(share_str)
        self._stats_label.setText("  ·  ".join(parts))

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
        dlg = _SegmentEditDialog(seg, self.distinct_speakers(), self._i18n, parent=self)
        if dlg.exec():
            new_speaker, new_text = dlg.get_values()
            if new_text:
                self.segment_updated.emit(seg_id, new_speaker, new_text)

    def _open_bulk_rename_picker(self) -> None:
        speakers = self.distinct_speakers()
        if not speakers:
            return
        old_speaker = speakers[0]
        if len(speakers) > 1:
            chosen, ok = QInputDialog.getItem(
                self,
                self._i18n.t("dlg_rename_title"),
                self._i18n.t("dlg_speaker"),
                speakers,
                0,
                False,
            )
            if not ok or not chosen:
                return
            old_speaker = chosen
        self._prompt_bulk_rename(old_speaker)

    def _prompt_bulk_rename(self, old_speaker: str) -> None:
        new_name, ok = QInputDialog.getText(
            self,
            self._i18n.t("dlg_rename_title"),
            self._i18n.t("dlg_rename_prompt", speaker=old_speaker),
            text=old_speaker,
        )
        if ok and new_name.strip() and new_name.strip() != old_speaker:
            self.speaker_bulk_renamed.emit(old_speaker, new_name.strip())

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
        bm_act = menu.addAction(
            self._i18n.t("ctx_unbookmark" if seg.is_bookmarked else "ctx_bookmark")
        )
        edit_act = menu.addAction(self._i18n.t("ctx_edit"))
        rename_act = menu.addAction(self._i18n.t("ctx_rename_all", speaker=seg.speaker))
        menu.addSeparator()
        del_act = menu.addAction(self._i18n.t("ctx_delete"))

        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen == bm_act:
            self.segment_bookmarked.emit(int(seg_id), not seg.is_bookmarked)
        elif chosen == edit_act:
            self._open_edit_dialog_by_id(int(seg_id))
        elif chosen == rename_act:
            self._prompt_bulk_rename(seg.speaker)
        elif chosen == del_act:
            self.segment_deleted.emit(int(seg_id))
