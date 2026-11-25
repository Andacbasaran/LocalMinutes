"""Studio 2.0 Left Sidebar Rail (228px) — Navigation, Meeting Archive & Privacy Status Card."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
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

from localminutes import __app_name__, __version__
from localminutes.export.exporter import format_timestamp
from localminutes.i18n import LanguageManager
from localminutes.models import Meeting
from localminutes.ui.studio_widgets import (
    SidebarNavButton,
    create_app_pixmap,
    make_flat_icon,
)


class _ArchiveRowWidget(QWidget):
    """Compact two-line archive entry displaying meeting title, template tag, date, and duration."""

    def __init__(self, meeting: Meeting, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(3)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(5)

        title_lbl = QLabel(meeting.title)
        title_lbl.setStyleSheet(
            "color: #F4F4F5; font-size: 12px; font-weight: 600; background: transparent;"
        )
        title_lbl.setWordWrap(False)
        title_lbl.setMaximumWidth(158)
        top.addWidget(title_lbl, 1)

        if meeting.summary is not None:
            dot = QFrame()
            dot.setFixedSize(6, 6)
            dot.setStyleSheet("background-color: #10B981; border-radius: 3px; border: none;")
            top.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        lay.addLayout(top)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(5)

        date_str = meeting.created_at.replace("T", " ")[5:16] if len(meeting.created_at) >= 16 else meeting.created_at
        date_lbl = QLabel(date_str)
        date_lbl.setStyleSheet("color: #71717A; font-size: 10.5px; background: transparent;")
        meta.addWidget(date_lbl)

        tmpl_lbl = QLabel(meeting.template.upper()[:4])
        tmpl_lbl.setStyleSheet(
            "color: #A1A1AA; background-color: #1B1B22; border: 1px solid #2A2A33; "
            "border-radius: 3px; padding: 0px 4px; font-size: 9px; font-weight: 700;"
        )
        meta.addWidget(tmpl_lbl)
        meta.addStretch()

        dur_lbl = QLabel(format_timestamp(meeting.duration_sec))
        dur_lbl.setStyleSheet(
            "color: #34D399; font-size: 10px; font-weight: 600; background: transparent;"
        )
        meta.addWidget(dur_lbl)

        lay.addLayout(meta)


class ArchiveSidebar(QFrame):
    """Left 228px Studio 2.0 sidebar rail with workspace views, searchable archive, and privacy card."""

    view_changed = pyqtSignal(int)  # 0=Studio, 1=Tasks, 2=Settings
    meeting_selected = pyqtSignal(int)
    new_meeting_requested = pyqtSignal()
    demo_meeting_requested = pyqtSignal()
    delete_meeting_requested = pyqtSignal(int)
    export_json_requested = pyqtSignal(int)
    search_changed = pyqtSignal(str)

    def __init__(self, i18n: LanguageManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._i18n = i18n
        self.setObjectName("SidebarRail")
        self.setFixedWidth(238)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        # --- Brand Row ---
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(2, 0, 2, 2)
        brand_row.setSpacing(9)

        logo_lbl = QLabel()
        logo_lbl.setPixmap(create_app_pixmap(28))
        logo_lbl.setFixedSize(28, 28)
        logo_lbl.setStyleSheet("border: none; background: transparent;")
        brand_row.addWidget(logo_lbl)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(0)
        title_line = QHBoxLayout()
        title_line.setSpacing(6)
        brand_name = QLabel(__app_name__)
        brand_name.setStyleSheet(
            "color: #FAFAFA; font-size: 13.5px; font-weight: 800; letter-spacing: -0.3px;"
        )
        title_line.addWidget(brand_name)

        ver_badge = QLabel(f"v{__version__}")
        ver_badge.setStyleSheet(
            "color: #34D399; background-color: rgba(16, 185, 129, 0.14); "
            "border: 1px solid rgba(16, 185, 129, 0.30); border-radius: 4px; "
            "padding: 1px 5px; font-size: 9px; font-weight: 700;"
        )
        title_line.addWidget(ver_badge)
        title_line.addStretch()
        brand_col.addLayout(title_line)

        self._tagline_lbl = QLabel(i18n.t("app_tagline"))
        self._tagline_lbl.setStyleSheet("color: #71717A; font-size: 10px;")
        brand_col.addWidget(self._tagline_lbl)
        brand_row.addLayout(brand_col, 1)
        layout.addLayout(brand_row)

        # --- Workspace Navigation ---
        self._ws_eyebrow = QLabel(i18n.t("nav_workspace_section"))
        self._ws_eyebrow.setObjectName("EyebrowLabel")
        layout.addWidget(self._ws_eyebrow)

        nav_box = QVBoxLayout()
        nav_box.setSpacing(3)
        self.btn_nav_studio = SidebarNavButton(i18n.t("nav_studio"))
        self.btn_nav_tasks = SidebarNavButton(i18n.t("nav_tasks"))
        self.btn_nav_settings = SidebarNavButton(i18n.t("nav_settings"))

        self._nav_buttons = [self.btn_nav_studio, self.btn_nav_tasks, self.btn_nav_settings]
        for idx, btn in enumerate(self._nav_buttons):
            btn.clicked.connect(lambda _c=False, i=idx: self._select_nav(i))
            nav_box.addWidget(btn)
        self.set_active_view(0)
        layout.addLayout(nav_box)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("background-color: #202026; max-height: 1px; border: none;")
        layout.addWidget(div)

        # --- Meeting Archive Section ---
        arc_hdr = QHBoxLayout()
        arc_hdr.setSpacing(6)
        self._arc_eyebrow = QLabel(i18n.t("nav_archive_section"))
        self._arc_eyebrow.setObjectName("EyebrowLabel")
        arc_hdr.addWidget(self._arc_eyebrow)
        arc_hdr.addStretch()
        self._count_label = QLabel(i18n.t("archive_count", count=0))
        self._count_label.setStyleSheet("color: #71717A; font-size: 10px;")
        arc_hdr.addWidget(self._count_label)
        layout.addLayout(arc_hdr)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)

        self._new_btn = QPushButton(i18n.t("archive_new_btn"))
        self._new_btn.setObjectName("PrimaryButton")
        self._new_btn.setIcon(make_flat_icon("plus", "#041710", 11))
        self._new_btn.setIconSize(QSize(11, 11))
        self._new_btn.setFixedHeight(28)
        self._new_btn.setStyleSheet("padding: 3px 8px; font-size: 11px;")
        self._new_btn.clicked.connect(self.new_meeting_requested.emit)
        action_row.addWidget(self._new_btn, 1)

        self._demo_btn = QPushButton(i18n.t("archive_demo_btn"))
        self._demo_btn.setObjectName("GhostButton")
        self._demo_btn.setIcon(make_flat_icon("sparkles", "#34D399", 11))
        self._demo_btn.setIconSize(QSize(11, 11))
        self._demo_btn.setFixedHeight(28)
        self._demo_btn.setStyleSheet("padding: 3px 8px; font-size: 11px;")
        self._demo_btn.clicked.connect(self.demo_meeting_requested.emit)
        action_row.addWidget(self._demo_btn)
        layout.addLayout(action_row)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(i18n.t("archive_search_ph"))
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setFixedHeight(30)
        self._search_input.textChanged.connect(self.search_changed.emit)
        layout.addWidget(self._search_input)

        self._list = QListWidget()
        self._list.setObjectName("ArchiveList")
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._open_context_menu)
        self._list.currentItemChanged.connect(self._on_current_changed)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list, 1)

        # --- Bottom Pinned Privacy & Engine Status Card ---
        privacy_card = QFrame()
        privacy_card.setObjectName("PrivacyCard")
        p_lay = QVBoxLayout(privacy_card)
        p_lay.setContentsMargins(10, 9, 10, 9)
        p_lay.setSpacing(3)

        p_top = QHBoxLayout()
        p_top.setSpacing(6)
        shield_lbl = QLabel()
        shield_lbl.setPixmap(make_flat_icon("shield", "#10B981", 13).pixmap(13, 13))
        p_top.addWidget(shield_lbl)

        self._privacy_title = QLabel(i18n.t("privacy_title"))
        self._privacy_title.setStyleSheet(
            "color: #34D399; font-size: 9.5px; font-weight: 800; letter-spacing: 0.7px;"
        )
        p_top.addWidget(self._privacy_title)
        p_top.addStretch()
        p_lay.addLayout(p_top)

        self._privacy_line = QLabel(i18n.t("privacy_line_online"))
        self._privacy_line.setStyleSheet("color: #E4E4E7; font-size: 10.5px; font-weight: 600;")
        p_lay.addWidget(self._privacy_line)

        self._engine_line = QLabel(i18n.t("privacy_engine", model="small", compute="INT8"))
        self._engine_line.setStyleSheet("color: #86EFAC; font-size: 10px;")
        p_lay.addWidget(self._engine_line)

        layout.addWidget(privacy_card)

    def _select_nav(self, index: int) -> None:
        self.set_active_view(index)
        self.view_changed.emit(index)

    def set_active_view(self, index: int) -> None:
        for i, btn in enumerate(self._nav_buttons):
            btn.set_active(i == index)

    def set_recording_badge(self, recording: bool) -> None:
        if recording:
            self.btn_nav_studio.set_badge("REC", kind="live")
        else:
            self.btn_nav_studio.set_badge("", kind="muted")

    def set_open_tasks_badge(self, count: int) -> None:
        if count > 0:
            self.btn_nav_tasks.set_badge(str(count), kind="emerald")
        else:
            self.btn_nav_tasks.set_badge("", kind="muted")

    def update_privacy_status(self, model: str, compute: str, air_gapped: bool) -> None:
        self._privacy_line.setText(
            self._i18n.t("privacy_line_airgap" if air_gapped else "privacy_line_online")
        )
        self._engine_line.setText(
            self._i18n.t("privacy_engine", model=model, compute=compute.upper())
        )

    def retranslate(self, i18n: LanguageManager, model: str, compute: str, air_gapped: bool) -> None:
        self._i18n = i18n
        self._tagline_lbl.setText(i18n.t("app_tagline"))
        self._ws_eyebrow.setText(i18n.t("nav_workspace_section"))
        self.btn_nav_studio.set_nav_text(i18n.t("nav_studio"))
        self.btn_nav_tasks.set_nav_text(i18n.t("nav_tasks"))
        self.btn_nav_settings.set_nav_text(i18n.t("nav_settings"))
        self._arc_eyebrow.setText(i18n.t("nav_archive_section"))
        self._new_btn.setText(i18n.t("archive_new_btn"))
        self._demo_btn.setText(i18n.t("archive_demo_btn"))
        self._search_input.setPlaceholderText(i18n.t("archive_search_ph"))
        self._privacy_title.setText(i18n.t("privacy_title"))
        self._count_label.setText(i18n.t("archive_count", count=self._list.count()))
        self.update_privacy_status(model, compute, air_gapped)

    def current_search_query(self) -> str:
        return self._search_input.text()

    def set_meetings(self, meetings: list[Meeting], selected_id: int | None = None) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        selected_row = -1
        for idx, m in enumerate(meetings):
            item = QListWidgetItem(self._list)
            item.setData(Qt.ItemDataRole.UserRole, m.id)
            row_widget = _ArchiveRowWidget(m)
            item.setSizeHint(QSize(190, 48))
            self._list.addItem(item)
            self._list.setItemWidget(item, row_widget)
            if selected_id is not None and m.id == selected_id:
                selected_row = idx
        if selected_row >= 0:
            self._list.setCurrentRow(selected_row)
        self._list.blockSignals(False)
        self._count_label.setText(self._i18n.t("archive_count", count=len(meetings)))

    def _on_current_changed(
        self, current: QListWidgetItem | None, _prev: QListWidgetItem | None
    ) -> None:
        if current is None:
            return
        meeting_id = current.data(Qt.ItemDataRole.UserRole)
        if meeting_id is not None:
            self.set_active_view(0)
            self.view_changed.emit(0)
            self.meeting_selected.emit(int(meeting_id))

    def _on_item_clicked(self, item: QListWidgetItem | None) -> None:
        """Ensure clicking the already-selected meeting returns from Tasks/Settings to Studio."""
        if item is None:
            return
        meeting_id = item.data(Qt.ItemDataRole.UserRole)
        if meeting_id is not None:
            self.set_active_view(0)
            self.view_changed.emit(0)
            self.meeting_selected.emit(int(meeting_id))

    def _open_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        meeting_id = item.data(Qt.ItemDataRole.UserRole)
        if meeting_id is None:
            return
        menu = QMenu(self)
        export_act = menu.addAction(self._i18n.t("archive_duplicate"))
        menu.addSeparator()
        delete_act = menu.addAction(self._i18n.t("archive_delete"))
        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen == delete_act:
            self.delete_meeting_requested.emit(int(meeting_id))
        elif chosen == export_act:
            self.export_json_requested.emit(int(meeting_id))
