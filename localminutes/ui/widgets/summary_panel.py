"""Studio 2.0 4-Tab Intelligence Dock — Summary + Action Items, Notes, Local Ask AI, and Insights."""

from __future__ import annotations

import html
from typing import Optional

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from localminutes.analytics import compute_meeting_stats
from localminutes.export.exporter import format_timestamp
from localminutes.i18n import LanguageManager
from localminutes.models import (
    SUMMARY_TEMPLATES,
    ActionItem,
    QAResponse,
    SummaryResult,
    TranscriptSegment,
    get_template_meta,
)
from localminutes.ui.studio_widgets import FlatComboBox, make_flat_icon
from localminutes.ui.widgets.transcript_view import speaker_color_tokens


class SummaryPanel(QWidget):
    """Right-hand 4-tab intelligence dock: Summary & Action Items, Notes, Ask AI, Insights."""

    summarize_requested = pyqtSignal(str)  # template_key
    template_changed = pyqtSignal(str)
    notes_changed = pyqtSignal(str)
    enhance_notes_requested = pyqtSignal()
    action_item_toggled = pyqtSignal(int, bool)  # action_id, completed
    action_item_added = pyqtSignal(str)  # raw text
    action_item_deleted = pyqtSignal(int)  # action_id
    qa_requested = pyqtSignal(str)  # question
    citation_clicked = pyqtSignal(object, float)  # segment_id | None, timestamp_sec

    def __init__(self, i18n: LanguageManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._i18n = i18n
        self.setMinimumWidth(420)
        self._summary: Optional[SummaryResult] = None
        self._action_items: list[ActionItem] = []
        self._segments: list[TranscriptSegment] = []
        self._notes_dirty = False
        self._is_summarizing = False
        self._is_qa_busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 12, 10)
        layout.setSpacing(8)

        self._tabs = QTabWidget()
        self._tabs.setUsesScrollButtons(False)
        layout.addWidget(self._tabs, 1)

        self._build_summary_tab()
        self._build_notes_tab()
        self._build_qa_tab()
        self._build_insights_tab()

    # ------------------------------------------------------------------
    # Tab 1: Summary & Interactive Action Items
    # ------------------------------------------------------------------

    def _build_summary_tab(self) -> None:
        tab = QWidget()
        s_lay = QVBoxLayout(tab)
        s_lay.setContentsMargins(10, 10, 10, 10)
        s_lay.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)
        self._template_combo = FlatComboBox()
        self._populate_templates()
        self._template_combo.currentIndexChanged.connect(self._on_template_changed)
        header.addWidget(self._template_combo, 1)

        self._copy_btn = QPushButton(self._i18n.t("btn_copy"))
        self._copy_btn.setObjectName("GhostButton")
        self._copy_btn.setIcon(make_flat_icon("copy", "#A1A1AA", 12))
        self._copy_btn.setIconSize(QSize(12, 12))
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._copy_summary)
        header.addWidget(self._copy_btn)

        self._gen_btn = QPushButton(self._i18n.t("btn_summarize"))
        self._gen_btn.setObjectName("PrimaryButton")
        self._gen_btn.setIcon(make_flat_icon("sparkles", "#041710", 12))
        self._gen_btn.setIconSize(QSize(12, 12))
        self._gen_btn.setToolTip("Generate structured summary & action items (Ctrl+G)")
        self._gen_btn.clicked.connect(self._emit_summarize)
        header.addWidget(self._gen_btn)
        s_lay.addLayout(header)

        self._meta_label = QLabel(self._i18n.t("summary_empty_meta"))
        self._meta_label.setObjectName("MutedLabel")
        self._meta_label.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        s_lay.addWidget(self._meta_label)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setPlaceholderText(self._i18n.t("summary_placeholder"))
        s_lay.addWidget(self._browser, 3)

        # Interactive Persisted Action Items Box
        action_box = QFrame()
        action_box.setObjectName("StudioCard")
        ab_lay = QVBoxLayout(action_box)
        ab_lay.setContentsMargins(10, 8, 10, 8)
        ab_lay.setSpacing(6)

        ahdr = QHBoxLayout()
        self._ai_hdr_lbl = QLabel(self._i18n.t("summary_action_items_hdr"))
        self._ai_hdr_lbl.setObjectName("EyebrowLabel")
        ahdr.addWidget(self._ai_hdr_lbl)
        ahdr.addStretch()
        self._ai_count_lbl = QLabel("0 / 0")
        self._ai_count_lbl.setStyleSheet("color: #34D399; font-size: 10.5px; font-weight: 700;")
        ahdr.addWidget(self._ai_count_lbl)
        ab_lay.addLayout(ahdr)

        self._ai_scroll = QScrollArea()
        self._ai_scroll.setWidgetResizable(True)
        self._ai_scroll.setMaximumHeight(145)
        self._ai_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._ai_scroll.viewport().setStyleSheet("background: transparent;")
        self._ai_container = QWidget()
        self._ai_container.setStyleSheet("background: transparent;")
        self._ai_list_layout = QVBoxLayout(self._ai_container)
        self._ai_list_layout.setContentsMargins(0, 0, 0, 0)
        self._ai_list_layout.setSpacing(4)
        self._ai_list_layout.addStretch()
        self._ai_scroll.setWidget(self._ai_container)
        ab_lay.addWidget(self._ai_scroll)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self._ai_input = QLineEdit()
        self._ai_input.setPlaceholderText(self._i18n.t("action_add_ph"))
        self._ai_input.setFixedHeight(28)
        self._ai_input.returnPressed.connect(self._submit_new_action_item)
        add_row.addWidget(self._ai_input, 1)

        add_btn = QPushButton()
        add_btn.setObjectName("GhostButton")
        add_btn.setIcon(make_flat_icon("plus", "#34D399", 12))
        add_btn.setIconSize(QSize(12, 12))
        add_btn.setFixedSize(28, 28)
        add_btn.clicked.connect(self._submit_new_action_item)
        add_row.addWidget(add_btn)
        ab_lay.addLayout(add_row)

        s_lay.addWidget(action_box, 2)
        self._tabs.addTab(
            tab, make_flat_icon("sparkles", "#34D399", 12), self._i18n.t("dock_tab_summary")
        )

    def _populate_templates(self) -> None:
        prev_key = self._template_combo.currentData() or "meeting"
        self._template_combo.blockSignals(True)
        self._template_combo.clear()
        for key in SUMMARY_TEMPLATES:
            meta = get_template_meta(key, lang=self._i18n.lang)
            self._template_combo.addItem(meta["label"], key)
        for i in range(self._template_combo.count()):
            if self._template_combo.itemData(i) == prev_key:
                self._template_combo.setCurrentIndex(i)
                break
        self._template_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Tab 2: Granola-Style Timestamped Notes
    # ------------------------------------------------------------------

    def _build_notes_tab(self) -> None:
        tab = QWidget()
        n_lay = QVBoxLayout(tab)
        n_lay.setContentsMargins(10, 10, 10, 10)
        n_lay.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self._ts_btn = QPushButton(self._i18n.t("notes_timestamp_btn"))
        self._ts_btn.setObjectName("GhostButton")
        self._ts_btn.setIcon(make_flat_icon("clock", "#34D399", 12))
        self._ts_btn.setIconSize(QSize(12, 12))
        self._ts_btn.setToolTip("Insert current meeting timestamp (Ctrl+T)")
        toolbar.addWidget(self._ts_btn)

        self._enhance_btn = QPushButton(self._i18n.t("notes_enhance_btn"))
        self._enhance_btn.setObjectName("PrimaryButton")
        self._enhance_btn.setIcon(make_flat_icon("sparkles", "#041710", 12))
        self._enhance_btn.setIconSize(QSize(12, 12))
        self._enhance_btn.clicked.connect(self.enhance_notes_requested.emit)
        toolbar.addWidget(self._enhance_btn)
        toolbar.addStretch()
        n_lay.addLayout(toolbar)

        self._notes_hint = QLabel(self._i18n.t("notes_hint"))
        self._notes_hint.setObjectName("MutedLabel")
        self._notes_hint.setWordWrap(True)
        n_lay.addWidget(self._notes_hint)

        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setPlaceholderText(self._i18n.t("notes_placeholder"))
        n_lay.addWidget(self._notes_edit, 1)

        self._notes_debounce = QTimer(self)
        self._notes_debounce.setSingleShot(True)
        self._notes_debounce.setInterval(450)
        self._notes_debounce.timeout.connect(self._flush_notes_signal)
        self._notes_edit.textChanged.connect(self._on_notes_text_edited)

        self._tabs.addTab(
            tab, make_flat_icon("notes", "#A1A1AA", 12), self._i18n.t("dock_tab_notes")
        )

    def connect_timestamp_button(self, callback) -> None:
        self._ts_btn.clicked.connect(callback)

    def insert_timestamp_marker(self, seconds: float) -> None:
        ts = format_timestamp(seconds)
        cursor = self._notes_edit.textCursor()
        prefix = "" if (cursor.atBlockStart() or not self._notes_edit.toPlainText()) else "\n"
        cursor.insertText(f"{prefix}- [{ts}] ")
        self._notes_edit.setTextCursor(cursor)
        self._notes_edit.setFocus()
        self._tabs.setCurrentIndex(1)

    def _on_notes_text_edited(self) -> None:
        self._notes_dirty = True
        self._notes_debounce.start()

    def _flush_notes_signal(self) -> None:
        if self._notes_dirty:
            self._notes_dirty = False
            self.notes_changed.emit(self._notes_edit.toPlainText())

    def flush_pending_notes(self) -> Optional[str]:
        """
        Immediately cancel pending debounce timer and return unsaved notes text (if dirty)
        so MainWindow persists edits to the PREVIOUS meeting BEFORE switching meetings.
        """
        if self._notes_debounce.isActive():
            self._notes_debounce.stop()
        if self._notes_dirty:
            self._notes_dirty = False
            return self._notes_edit.toPlainText()
        return None

    def set_notes(self, text: str) -> None:
        if self._notes_debounce.isActive():
            self._notes_debounce.stop()
        self._notes_dirty = False
        self._notes_edit.blockSignals(True)
        self._notes_edit.setPlainText(text)
        self._notes_edit.blockSignals(False)

    def apply_enhanced_notes(self, text: str) -> None:
        """Apply enhanced notes via a single QTextCursor edit block so Ctrl+Z undo is preserved."""
        if self._notes_debounce.isActive():
            self._notes_debounce.stop()
        self._notes_dirty = False
        self._notes_edit.blockSignals(True)
        try:
            cursor = self._notes_edit.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(text)
            cursor.endEditBlock()
            self._notes_edit.setTextCursor(cursor)
        finally:
            self._notes_edit.blockSignals(False)

    def set_enhance_busy(self, busy: bool) -> None:
        self._enhance_btn.setEnabled(not busy)

    # ------------------------------------------------------------------
    # Tab 3: Ask This Meeting (Local Q&A with Clickable Citations)
    # ------------------------------------------------------------------

    def _build_qa_tab(self) -> None:
        tab = QWidget()
        q_lay = QVBoxLayout(tab)
        q_lay.setContentsMargins(10, 10, 10, 10)
        q_lay.setSpacing(8)

        self._qa_hint = QLabel(self._i18n.t("qa_hint"))
        self._qa_hint.setObjectName("MutedLabel")
        self._qa_hint.setWordWrap(True)
        q_lay.addWidget(self._qa_hint)

        # Quick suggestion pills
        quick_row = QHBoxLayout()
        quick_row.setSpacing(5)
        self._qa_quick_btns: list[QPushButton] = []
        for qk in ("qa_quick_1", "qa_quick_2", "qa_quick_3"):
            btn = QPushButton(self._i18n.t(qk))
            btn.setObjectName("FilterPill")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, b=btn: self._ask_preset(b.text()))
            self._qa_quick_btns.append(btn)
            quick_row.addWidget(btn)
        quick_row.addStretch()
        q_lay.addLayout(quick_row)

        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self._qa_input = QLineEdit()
        self._qa_input.setPlaceholderText(self._i18n.t("qa_input_ph"))
        self._qa_input.setFixedHeight(32)
        self._qa_input.returnPressed.connect(self._submit_qa)
        input_row.addWidget(self._qa_input, 1)

        self._qa_ask_btn = QPushButton(self._i18n.t("qa_ask_btn"))
        self._qa_ask_btn.setObjectName("PrimaryButton")
        self._qa_ask_btn.setFixedHeight(32)
        self._qa_ask_btn.clicked.connect(self._submit_qa)
        input_row.addWidget(self._qa_ask_btn)
        q_lay.addLayout(input_row)

        self._qa_meta = QLabel("")
        self._qa_meta.setObjectName("MutedLabel")
        q_lay.addWidget(self._qa_meta)

        self._qa_browser = QTextBrowser()
        self._qa_browser.setOpenExternalLinks(False)
        q_lay.addWidget(self._qa_browser, 2)

        self._qa_cit_hdr = QLabel(self._i18n.t("qa_citations_hdr"))
        self._qa_cit_hdr.setObjectName("EyebrowLabel")
        q_lay.addWidget(self._qa_cit_hdr)

        self._qa_cit_scroll = QScrollArea()
        self._qa_cit_scroll.setWidgetResizable(True)
        self._qa_cit_scroll.setMaximumHeight(135)
        self._qa_cit_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._qa_cit_scroll.viewport().setStyleSheet("background: transparent;")
        self._qa_cit_container = QWidget()
        self._qa_cit_container.setStyleSheet("background: transparent;")
        self._qa_cit_layout = QVBoxLayout(self._qa_cit_container)
        self._qa_cit_layout.setContentsMargins(0, 0, 0, 0)
        self._qa_cit_layout.setSpacing(4)
        self._qa_cit_layout.addStretch()
        self._qa_cit_scroll.setWidget(self._qa_cit_container)
        q_lay.addWidget(self._qa_cit_scroll, 1)

        self._tabs.addTab(
            tab, make_flat_icon("chat", "#38BDF8", 12), self._i18n.t("dock_tab_qa")
        )

    def _ask_preset(self, text: str) -> None:
        if self._is_qa_busy:
            return
        self._qa_input.setText(text)
        self._submit_qa()

    def _submit_qa(self) -> None:
        if self._is_qa_busy:
            return
        q = self._qa_input.text().strip()
        if q:
            self.qa_requested.emit(q)

    def set_qa_busy(self, busy: bool) -> None:
        self._is_qa_busy = bool(busy)
        self._qa_ask_btn.setEnabled(not busy)
        for btn in self._qa_quick_btns:
            btn.setEnabled(not busy)
        self._qa_ask_btn.setText(self._i18n.t("qa_asking" if busy else "qa_ask_btn"))

    def set_qa_response(self, response: Optional[QAResponse]) -> None:
        while self._qa_cit_layout.count():
            item = self._qa_cit_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        if response is None:
            self._qa_meta.setText("")
            self._qa_browser.clear()
            self._qa_cit_layout.addStretch()
            return

        self._qa_meta.setText(f"{response.model_used}  ·  {len(response.citations)} sources")
        ans_html = html.escape(response.answer).replace("\n", "<br>")
        self._qa_browser.setHtml(
            f"<div style='color:#FAFAFA; font-size:12.5px; line-height:1.5;'>{ans_html}</div>"
        )

        for cit in response.citations:
            ts = format_timestamp(cit.timestamp_sec)
            snippet_short = (cit.snippet[:86] + "...") if len(cit.snippet) > 88 else cit.snippet
            btn = QPushButton(f"[{ts}] {cit.speaker}: {snippet_short}")
            btn.setObjectName("GhostButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { text-align: left; background-color: #121216; border: 1px solid #24242A; "
                "border-left: 3px solid #10B981; border-radius: 6px; padding: 6px 8px; "
                "color: #D4D4D8; font-size: 11px; font-weight: 500; }"
                "QPushButton:hover { background-color: #1B2420; border-color: #10B981; color: #FAFAFA; }"
            )
            btn.clicked.connect(
                lambda _c=False, sid=cit.segment_id, tsec=cit.timestamp_sec: self.citation_clicked.emit(
                    sid, tsec
                )
            )
            self._qa_cit_layout.addWidget(btn)
        self._qa_cit_layout.addStretch()

    # ------------------------------------------------------------------
    # Tab 4: Speaker Insights & Speaking Pace
    # ------------------------------------------------------------------

    def _build_insights_tab(self) -> None:
        tab = QWidget()
        i_lay = QVBoxLayout(tab)
        i_lay.setContentsMargins(10, 10, 10, 10)
        i_lay.setSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(8)
        self._ins_talk = self._make_mini_stat(self._i18n.t("insights_talk_time"), "00:00", "#10B981")
        self._ins_pace = self._make_mini_stat(self._i18n.t("insights_pace"), "0 WPM", "#38BDF8")
        self._ins_words = self._make_mini_stat(self._i18n.t("insights_words"), "0", "#FAFAFA")
        self._ins_stars = self._make_mini_stat(self._i18n.t("insights_bookmarks"), "0", "#F59E0B")
        grid.addWidget(self._ins_talk[0], 0, 0)
        grid.addWidget(self._ins_pace[0], 0, 1)
        grid.addWidget(self._ins_words[0], 1, 0)
        grid.addWidget(self._ins_stars[0], 1, 1)
        i_lay.addLayout(grid)

        self._ins_dist_hdr = QLabel(self._i18n.t("insights_speaker_share"))
        self._ins_dist_hdr.setObjectName("EyebrowLabel")
        i_lay.addWidget(self._ins_dist_hdr)

        self._ins_bars_box = QWidget()
        self._ins_bars_layout = QVBoxLayout(self._ins_bars_box)
        self._ins_bars_layout.setContentsMargins(0, 0, 0, 0)
        self._ins_bars_layout.setSpacing(8)
        self._ins_bars_layout.addStretch()
        i_lay.addWidget(self._ins_bars_box, 1)

        self._tabs.addTab(
            tab, make_flat_icon("chart", "#A78BFA", 12), self._i18n.t("dock_tab_insights")
        )

    @staticmethod
    def _make_mini_stat(title: str, val: str, accent: str) -> tuple[QFrame, QLabel, QLabel]:
        card = QFrame()
        card.setObjectName("StudioCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)
        t_lbl = QLabel(title)
        t_lbl.setStyleSheet("color: #71717A; font-size: 10.5px; font-weight: 600;")
        v_lbl = QLabel(val)
        v_lbl.setStyleSheet(f"color: {accent}; font-size: 16px; font-weight: 700;")
        lay.addWidget(t_lbl)
        lay.addWidget(v_lbl)
        return card, t_lbl, v_lbl

    def update_insights(self, segments: list[TranscriptSegment]) -> None:
        self._segments = list(segments)
        stats = compute_meeting_stats(segments)
        self._ins_talk[2].setText(format_timestamp(stats.total_talk_sec))
        self._ins_pace[2].setText(f"{stats.words_per_minute:.0f} WPM")
        self._ins_words[2].setText(f"{stats.total_words:,}")
        self._ins_stars[2].setText(str(stats.bookmarked_count))

        while self._ins_bars_layout.count():
            item = self._ins_bars_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        if not stats.speaker_word_share:
            empty = QLabel(self._i18n.t("insights_empty"))
            empty.setObjectName("MutedLabel")
            empty.setWordWrap(True)
            self._ins_bars_layout.addWidget(empty)
            self._ins_bars_layout.addStretch()
            return

        for spk, pct in sorted(stats.speaker_word_share.items(), key=lambda kv: kv[1], reverse=True):
            accent_hex, _, _ = speaker_color_tokens(spk)
            row_card = QFrame()
            row_card.setObjectName("StudioCard")
            rl = QVBoxLayout(row_card)
            rl.setContentsMargins(10, 7, 10, 7)
            rl.setSpacing(5)

            top = QHBoxLayout()
            name_lbl = QLabel(spk)
            name_lbl.setStyleSheet("color: #FAFAFA; font-size: 12px; font-weight: 600;")
            top.addWidget(name_lbl)
            top.addStretch()

            sec = stats.speaker_talk_sec.get(spk, 0.0)
            wpm = stats.speaker_wpm.get(spk, 0.0)
            meta_lbl = QLabel(f"{pct:.0f}%  ·  {format_timestamp(sec)}  ·  {wpm:.0f} WPM")
            meta_lbl.setStyleSheet("color: #A1A1AA; font-size: 11px;")
            top.addWidget(meta_lbl)
            rl.addLayout(top)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(max(3, int(round(pct))))
            bar.setTextVisible(False)
            bar.setFixedHeight(5)
            bar.setStyleSheet(
                f"QProgressBar {{ background:#1D1D23; border:none; border-radius:2px; }}"
                f"QProgressBar::chunk {{ background:{accent_hex}; border-radius:2px; }}"
            )
            rl.addWidget(bar)
            self._ins_bars_layout.addWidget(row_card)

        self._ins_bars_layout.addStretch()

    # ------------------------------------------------------------------
    # Action Items List Rendering
    # ------------------------------------------------------------------

    def set_action_items(self, items: list[ActionItem]) -> None:
        self._action_items = list(items)
        while self._ai_list_layout.count():
            child = self._ai_list_layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        done_cnt = sum(1 for a in items if a.completed)
        self._ai_count_lbl.setText(f"{done_cnt} / {len(items)}")

        for ai in items:
            row = QFrame()
            row.setStyleSheet(
                "QFrame { background-color: #101013; border: 1px solid #222228; border-radius: 6px; }"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(7, 5, 6, 5)
            rl.setSpacing(6)

            cb = QCheckBox()
            cb.setChecked(ai.completed)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            if ai.id is not None:
                cb.toggled.connect(
                    lambda checked, aid=ai.id: self.action_item_toggled.emit(aid, bool(checked))
                )
            rl.addWidget(cb)

            label_txt = f"{ai.assignee}: {ai.text}" if ai.assignee else ai.text
            lbl = QLabel(label_txt)
            lbl.setWordWrap(True)
            if ai.completed:
                lbl.setStyleSheet(
                    "color: #71717A; font-size: 11.5px; text-decoration: line-through; border: none;"
                )
            else:
                lbl.setStyleSheet("color: #E4E4E7; font-size: 11.5px; border: none;")
            rl.addWidget(lbl, 1)

            del_btn = QToolButton()
            del_btn.setIcon(make_flat_icon("close", "#71717A", 10))
            del_btn.setIconSize(QSize(10, 10))
            del_btn.setStyleSheet("QToolButton { background: transparent; border: none; }")
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if ai.id is not None:
                del_btn.clicked.connect(
                    lambda _c=False, aid=ai.id: self.action_item_deleted.emit(aid)
                )
            rl.addWidget(del_btn)
            self._ai_list_layout.addWidget(row)

        self._ai_list_layout.addStretch()

    def _submit_new_action_item(self) -> None:
        txt = self._ai_input.text().strip()
        if txt:
            self._ai_input.clear()
            self.action_item_added.emit(txt)

    # ------------------------------------------------------------------
    # Summary & Template Public API
    # ------------------------------------------------------------------

    def current_template(self) -> str:
        return str(self._template_combo.currentData() or "meeting")

    def set_template(self, template_key: str) -> None:
        self._template_combo.blockSignals(True)
        for i in range(self._template_combo.count()):
            if self._template_combo.itemData(i) == template_key:
                self._template_combo.setCurrentIndex(i)
                break
        self._template_combo.blockSignals(False)

    def _on_template_changed(self) -> None:
        self.template_changed.emit(self.current_template())

    def _emit_summarize(self) -> None:
        if self._is_summarizing:
            return
        self.summarize_requested.emit(self.current_template())

    def set_busy(self, busy: bool, message: str = "") -> None:
        self._is_summarizing = bool(busy)
        self._gen_btn.setEnabled(not busy)
        self._template_combo.setEnabled(not busy)
        if busy:
            self._gen_btn.setText(self._i18n.t("btn_summarizing"))
            if message:
                self._meta_label.setText(message)
        else:
            self._gen_btn.setText(self._i18n.t("btn_summarize"))

    def set_summary(self, summary: Optional[SummaryResult]) -> None:
        self._summary = summary
        if summary is None:
            self._browser.clear()
            self._copy_btn.setEnabled(False)
            self._meta_label.setText(self._i18n.t("summary_empty_meta"))
            return

        self._copy_btn.setEnabled(True)
        tmpl = get_template_meta(summary.template, lang=self._i18n.lang)
        model_info = summary.model_used or "local/extractive-offline"
        time_info = summary.generated_at.replace("T", " ")[:16] if summary.generated_at else ""
        self._meta_label.setText(f"{tmpl['label']}  ·  {model_info}  ·  {time_info}")

        sections: list[str] = []
        if summary.overview:
            sections.append(
                f"""
                <div style="margin-bottom:13px;">
                  <div style="color:#34D399; font-weight:700; font-size:11px; letter-spacing:0.6px; margin-bottom:4px;">
                    {html.escape(tmpl['overview_title'].upper())}
                  </div>
                  <div style="color:#F4F4F5; font-size:12.5px; line-height:1.48;">
                    {html.escape(summary.overview).replace(chr(10), '<br>')}
                  </div>
                </div>
                """
            )

        if summary.key_points:
            items = "".join(
                f"<li style='margin-bottom:4px;'>{html.escape(p)}</li>" for p in summary.key_points
            )
            sections.append(
                f"""
                <div style="margin-bottom:13px;">
                  <div style="color:#38BDF8; font-weight:700; font-size:11px; letter-spacing:0.6px; margin-bottom:4px;">
                    {html.escape(tmpl['key_points_title'].upper())}
                  </div>
                  <ul style="margin:0; padding-left:17px; color:#E4E4E7; font-size:12px;">{items}</ul>
                </div>
                """
            )

        if summary.decisions:
            items = "".join(
                f"<li style='margin-bottom:4px;'>{html.escape(d)}</li>" for d in summary.decisions
            )
            sections.append(
                f"""
                <div style="margin-bottom:8px;">
                  <div style="color:#FBBF24; font-weight:700; font-size:11px; letter-spacing:0.6px; margin-bottom:4px;">
                    {html.escape(tmpl['decisions_title'].upper())}
                  </div>
                  <ul style="margin:0; padding-left:17px; color:#E4E4E7; font-size:12px;">{items}</ul>
                </div>
                """
            )

        self._browser.setHtml("".join(sections))

    def _copy_summary(self) -> None:
        if not self._summary:
            return
        tmpl = get_template_meta(self._summary.template, lang=self._i18n.lang)
        lines: list[str] = []
        if self._summary.overview:
            lines.append(f"## {tmpl['overview_title']}\n" + self._summary.overview)
        if self._summary.key_points:
            lines.append(
                f"## {tmpl['key_points_title']}\n"
                + "\n".join(f"- {p}" for p in self._summary.key_points)
            )
        if self._summary.decisions:
            lines.append(
                f"## {tmpl['decisions_title']}\n"
                + "\n".join(f"- {d}" for d in self._summary.decisions)
            )
        if self._action_items:
            lines.append(
                f"## {tmpl['action_items_title']}\n"
                + "\n".join(
                    f"- [{'x' if a.completed else ' '}] "
                    f"{f'{a.assignee}: ' if a.assignee else ''}{a.text}"
                    for a in self._action_items
                )
            )
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("\n\n".join(lines))
            self._copy_btn.setText(self._i18n.t("btn_copied"))
            QTimer.singleShot(1500, self, self._reset_copy_button_label)

    def _reset_copy_button_label(self) -> None:
        self._copy_btn.setText(self._i18n.t("btn_copy"))

    def retranslate(self, i18n: LanguageManager) -> None:
        self._i18n = i18n
        self._tabs.setTabText(0, i18n.t("dock_tab_summary"))
        self._tabs.setTabText(1, i18n.t("dock_tab_notes"))
        self._tabs.setTabText(2, i18n.t("dock_tab_qa"))
        self._tabs.setTabText(3, i18n.t("dock_tab_insights"))
        self._populate_templates()
        self._copy_btn.setText(i18n.t("btn_copy"))
        self._gen_btn.setText(i18n.t("btn_summarize"))
        self._browser.setPlaceholderText(i18n.t("summary_placeholder"))
        self._ai_hdr_lbl.setText(i18n.t("summary_action_items_hdr"))
        self._ai_input.setPlaceholderText(i18n.t("action_add_ph"))
        self._ts_btn.setText(i18n.t("notes_timestamp_btn"))
        self._enhance_btn.setText(i18n.t("notes_enhance_btn"))
        self._notes_hint.setText(i18n.t("notes_hint"))
        self._notes_edit.setPlaceholderText(i18n.t("notes_placeholder"))
        self._qa_hint.setText(i18n.t("qa_hint"))
        self._qa_input.setPlaceholderText(i18n.t("qa_input_ph"))
        self._qa_ask_btn.setText(i18n.t("qa_ask_btn"))
        self._qa_cit_hdr.setText(i18n.t("qa_citations_hdr"))
        for btn, key in zip(self._qa_quick_btns, ("qa_quick_1", "qa_quick_2", "qa_quick_3")):
            btn.setText(i18n.t(key))
        self._ins_talk[1].setText(i18n.t("insights_talk_time"))
        self._ins_pace[1].setText(i18n.t("insights_pace"))
        self._ins_words[1].setText(i18n.t("insights_words"))
        self._ins_stars[1].setText(i18n.t("insights_bookmarks"))
        self._ins_dist_hdr.setText(i18n.t("insights_speaker_share"))
        if self._summary is not None:
            self.set_summary(self._summary)
        else:
            self._meta_label.setText(i18n.t("summary_empty_meta"))
        self.update_insights(self._segments)
