"""Studio 2.0 View 2 — Action Items & Archive Hub (cross-meeting KPIs & interactive checklist)."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from localminutes.i18n import LanguageManager
from localminutes.models import ActionItem
from localminutes.ui.studio_widgets import TelemetryCard, make_flat_icon


class TasksHubView(QWidget):
    """Cross-meeting Action Items checklist & Archive KPI dashboard."""

    action_item_toggled = pyqtSignal(int, bool)  # item_id, completed
    action_item_deleted = pyqtSignal(int)
    jump_to_meeting = pyqtSignal(int)  # meeting_id

    def __init__(self, i18n: LanguageManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._i18n = i18n
        self._all_items: list[ActionItem] = []
        self._filter_mode = "open"  # "open" | "done" | "all"
        self._query = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)

        # Header
        hdr = QVBoxLayout()
        hdr.setSpacing(3)
        self._title_lbl = QLabel(i18n.t("tasks_header"))
        self._title_lbl.setObjectName("PageTitle")
        hdr.addWidget(self._title_lbl)

        self._sub_lbl = QLabel(i18n.t("tasks_subtitle"))
        self._sub_lbl.setObjectName("MutedLabel")
        hdr.addWidget(self._sub_lbl)
        root.addLayout(hdr)

        # 4 Archive KPI TelemetryCards
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)
        self.card_meetings = TelemetryCard(
            i18n.t("kpi_total_meetings"), "LOCAL DB", "0", "SQLite FTS5", "#10B981", 20
        )
        self.card_hours = TelemetryCard(
            i18n.t("kpi_total_hours"), "DUAL-CH", "0.0 h", "16 kHz polyphase", "#38BDF8", 20
        )
        self.card_words = TelemetryCard(
            i18n.t("kpi_total_words"), "INDEXED", "0", "Full-text searchable", "#A78BFA", 20
        )
        self.card_open = TelemetryCard(
            i18n.t("kpi_open_tasks"), "ACTIVE", "0", "0 completed", "#F59E0B", 20
        )
        for card in (self.card_meetings, self.card_hours, self.card_words, self.card_open):
            kpi_row.addWidget(card, 1)
        root.addLayout(kpi_row)

        # Filter Controls
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self._filter_btns: dict[str, QPushButton] = {}
        for mode, key in (
            ("open", "tasks_filter_open"),
            ("done", "tasks_filter_done"),
            ("all", "tasks_filter_all"),
        ):
            btn = QPushButton(i18n.t(key))
            btn.setObjectName("FilterPill")
            btn.setCheckable(True)
            btn.setChecked(mode == self._filter_mode)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, m=mode: self._set_filter(m))
            self._filter_btns[mode] = btn
            ctrl.addWidget(btn)

        ctrl.addStretch()

        self._search = QLineEdit()
        self._search.setPlaceholderText(i18n.t("archive_search_ph"))
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(260)
        self._search.setFixedHeight(30)
        self._search.textChanged.connect(self._on_search)
        ctrl.addWidget(self._search)
        root.addLayout(ctrl)

        # Scrollable Task List
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._scroll.viewport().setStyleSheet("background: #0A0A0C;")
        self._container = QWidget()
        self._container.setStyleSheet("background: #0A0A0C;")
        self._list_lay = QVBoxLayout(self._container)
        self._list_lay.setContentsMargins(0, 0, 4, 0)
        self._list_lay.setSpacing(7)
        self._list_lay.addStretch()
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

    def refresh_data(self, insights: dict[str, Any], items: list[ActionItem]) -> None:
        self._all_items = list(items)
        total_m = int(insights.get("total_meetings", 0))
        dur_sec = float(insights.get("total_duration_sec", 0.0))
        total_words = int(insights.get("total_words", 0))
        open_cnt = int(insights.get("open_action_items", 0))
        done_cnt = int(insights.get("completed_action_items", 0))
        db_mb = float(insights.get("db_size_mb", 0.0))
        db_kb = float(insights.get("db_size_kb", 0.0))
        size_str = f"{db_mb:.2f} MB" if db_mb >= 0.1 else f"{db_kb:.0f} KB"

        hours_str = f"{dur_sec / 3600.0:.1f} h" if dur_sec >= 3600 else f"{dur_sec / 60.0:.0f} min"
        self.card_meetings.set_metric(
            str(total_m),
            sub_text=f"SQLite WAL · {size_str}",
            bar_pct=min(100, max(18, total_m * 15)),
        )
        self.card_hours.set_metric(
            hours_str,
            sub_text=f"{int(insights.get('total_segments', 0)):,} transcript segments",
            bar_pct=min(100, max(12, int(dur_sec / 60))),
        )
        self.card_words.set_metric(
            f"{total_words:,}",
            sub_text="FTS5 unicode61 indexed",
            bar_pct=min(100, max(12, int(total_words / 50))),
        )
        total_tasks = max(1, open_cnt + done_cnt)
        done_pct = int(round((done_cnt / total_tasks) * 100)) if (open_cnt + done_cnt) > 0 else 10
        self.card_open.set_metric(
            str(open_cnt),
            sub_text=f"{done_cnt} completed ({done_pct}%)",
            bar_pct=max(10, 100 - done_pct if open_cnt > 0 else 100),
        )
        self._render_list()

    def _set_filter(self, mode: str) -> None:
        self._filter_mode = mode
        for m, btn in self._filter_btns.items():
            btn.setChecked(m == mode)
        self._render_list()

    def _on_search(self, text: str) -> None:
        self._query = text.strip().lower()
        self._render_list()

    def _render_list(self) -> None:
        while self._list_lay.count():
            child = self._list_lay.takeAt(0)
            w = child.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        filtered: list[ActionItem] = []
        for ai in self._all_items:
            if self._filter_mode == "open" and ai.completed:
                continue
            if self._filter_mode == "done" and not ai.completed:
                continue
            if self._query:
                hay = f"{ai.text} {ai.assignee} {ai.meeting_title}".lower()
                if self._query not in hay:
                    continue
            filtered.append(ai)

        if not filtered:
            empty = QLabel(self._i18n.t("tasks_empty"))
            empty.setObjectName("MutedLabel")
            empty.setWordWrap(True)
            empty.setStyleSheet("padding: 20px; color: #71717A;")
            self._list_lay.addWidget(empty)
            self._list_lay.addStretch()
            return

        for ai in filtered:
            card = QFrame()
            card.setObjectName("StudioCard")
            lay = QHBoxLayout(card)
            lay.setContentsMargins(12, 10, 12, 10)
            lay.setSpacing(10)

            cb = QCheckBox()
            cb.setChecked(ai.completed)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            if ai.id is not None:
                cb.toggled.connect(
                    lambda checked, aid=ai.id: self.action_item_toggled.emit(aid, bool(checked))
                )
            lay.addWidget(cb)

            col = QVBoxLayout()
            col.setSpacing(3)
            txt_lbl = QLabel(ai.text)
            txt_lbl.setWordWrap(True)
            if ai.completed:
                txt_lbl.setStyleSheet(
                    "color: #71717A; font-size: 13px; text-decoration: line-through;"
                )
            else:
                txt_lbl.setStyleSheet("color: #FAFAFA; font-size: 13px; font-weight: 500;")
            col.addWidget(txt_lbl)

            meta_row = QHBoxLayout()
            meta_row.setSpacing(6)
            if ai.assignee:
                own = QLabel(ai.assignee)
                own.setStyleSheet(
                    "color: #34D399; background-color: rgba(16,185,129,0.14); "
                    "border-radius: 4px; padding: 1px 7px; font-size: 10.5px; font-weight: 700;"
                )
                meta_row.addWidget(own)
            if ai.due_date:
                due = QLabel(ai.due_date)
                due.setStyleSheet(
                    "color: #FBBF24; background-color: rgba(245,158,11,0.14); "
                    "border-radius: 4px; padding: 1px 7px; font-size: 10.5px; font-weight: 600;"
                )
                meta_row.addWidget(due)
            if ai.meeting_title:
                src = QLabel(ai.meeting_title)
                src.setStyleSheet("color: #71717A; font-size: 11px;")
                meta_row.addWidget(src)
            meta_row.addStretch()
            col.addLayout(meta_row)
            lay.addLayout(col, 1)

            if ai.meeting_id is not None:
                jump_btn = QPushButton(self._i18n.t("tasks_jump_btn"))
                jump_btn.setObjectName("GhostButton")
                jump_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                jump_btn.clicked.connect(
                    lambda _c=False, mid=ai.meeting_id: self.jump_to_meeting.emit(mid)
                )
                lay.addWidget(jump_btn)

            if ai.id is not None:
                del_btn = QToolButton()
                del_btn.setIcon(make_flat_icon("trash", "#71717A", 12))
                del_btn.setIconSize(QSize(12, 12))
                del_btn.setStyleSheet("QToolButton { background: transparent; border: none; }")
                del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                del_btn.clicked.connect(
                    lambda _c=False, aid=ai.id: self.action_item_deleted.emit(aid)
                )
                lay.addWidget(del_btn)

            self._list_lay.addWidget(card)

        self._list_lay.addStretch()

    def retranslate(self, i18n: LanguageManager) -> None:
        self._i18n = i18n
        self._title_lbl.setText(i18n.t("tasks_header"))
        self._sub_lbl.setText(i18n.t("tasks_subtitle"))
        self.card_meetings.set_title(i18n.t("kpi_total_meetings"))
        self.card_hours.set_title(i18n.t("kpi_total_hours"))
        self.card_words.set_title(i18n.t("kpi_total_words"))
        self.card_open.set_title(i18n.t("kpi_open_tasks"))
        self._filter_btns["open"].setText(i18n.t("tasks_filter_open"))
        self._filter_btns["done"].setText(i18n.t("tasks_filter_done"))
        self._filter_btns["all"].setText(i18n.t("tasks_filter_all"))
        self._search.setPlaceholderText(i18n.t("archive_search_ph"))
        self._render_list()
