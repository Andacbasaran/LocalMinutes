"""Studio 2.0 Main Window for LocalMinutes v1.0.0."""

from __future__ import annotations

import logging
import sqlite3
import tempfile
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from PyQt6.QtCore import QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFont, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from localminutes import __app_name__, __version__
from localminutes.audio.capture import DualAudioCapture, resample_to_16k_mono
from localminutes.config import (
    get_db_path,
    get_recordings_dir,
    load_settings,
    save_settings,
)
from localminutes.export.exporter import (
    build_demo_meeting,
    export_meeting,
    format_timestamp,
    parse_meeting_json,
)
from localminutes.hardware import (
    apply_thread_env_defaults,
    compute_runtime_tuning,
    detect_hardware_profile,
)
from localminutes.i18n import LanguageManager
from localminutes.models import (
    AppSettings,
    Meeting,
    QAResponse,
    SummaryResult,
    TranscriptSegment,
)
from localminutes.storage.database import MeetingDatabase
from localminutes.summarization.local_extractive import extractive_summarize
from localminutes.summarization.qa import ask_meeting, retrieve_bm25_citations
from localminutes.summarization.summarizer import (
    SummarizerError,
    enhance_meeting_notes,
    summarize_meeting,
)
from localminutes.transcription.engine import WhisperEngine
from localminutes.transcription.file_transcriber import (
    SUPPORTED_MEDIA_EXTENSIONS,
    transcribe_media_file,
)
from localminutes.transcription.live_pipeline import LiveTranscriptionPipeline
from localminutes.ui.studio_widgets import (
    DualWaveformMeter,
    create_app_icon,
    make_flat_icon,
)
from localminutes.ui.widgets.settings_view import SettingsView
from localminutes.ui.widgets.sidebar import ArchiveSidebar
from localminutes.ui.widgets.summary_panel import SummaryPanel
from localminutes.ui.widgets.tasks_hub import TasksHubView
from localminutes.ui.widgets.transcript_view import TranscriptView
from localminutes.updater import UpdateCheckerThread, UpdateInfo

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """LocalMinutes v1.0.0 PyQt6 Studio 2.0 main window."""

    _level_signal = pyqtSignal(str, float)
    _segment_signal = pyqtSignal(object)
    _status_signal = pyqtSignal(str)
    _error_signal = pyqtSignal(str)
    _summary_done_signal = pyqtSignal(int, object)
    _summary_error_signal = pyqtSignal(str)
    _enhance_done_signal = pyqtSignal(int, str, str)
    _enhance_error_signal = pyqtSignal(str)
    _qa_done_signal = pyqtSignal(int, object)
    _import_progress_signal = pyqtSignal(int)
    _import_done_signal = pyqtSignal(int, object, float, bool)
    _import_error_signal = pyqtSignal(str)
    _benchmark_done_signal = pyqtSignal(dict)

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        auto_check_updates: bool = True,
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__} — Bot-Free Offline Meeting Studio")
        self.setWindowIcon(create_app_icon())
        self.setAcceptDrops(True)

        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1440, 900)
        min_w = min(960, max(840, avail.width() - 40))
        min_h = min(600, max(520, avail.height() - 40))
        self.setMinimumSize(min_w, min_h)
        self.resize(min(1160, avail.width() - 40), min(700, avail.height() - 40))

        self._settings: AppSettings = load_settings()
        self._i18n = LanguageManager(self._settings.ui_language)
        self._hw = detect_hardware_profile(query_ct2=True)
        self._tuning = compute_runtime_tuning(
            self._hw,
            requested_profile=self._settings.performance_profile,
            preferred_compute_type=self._settings.whisper_compute_type,
        )
        apply_thread_env_defaults(self._tuning)

        self._db = MeetingDatabase(db_path or get_db_path())
        self._current_meeting: Optional[Meeting] = None

        self._engine: Optional[WhisperEngine] = None
        self._pipeline: Optional[LiveTranscriptionPipeline] = None
        self._pipeline_flush_thread: Optional[threading.Thread] = None
        self._capture: Optional[DualAudioCapture] = None
        self._import_cancel_event: Optional[threading.Event] = None
        self._update_thread: Optional[object] = None

        self._is_recording = False
        self._is_paused = False
        self._is_importing = False
        self._importing_meeting_id: Optional[int] = None
        self._is_summarizing = False
        self._is_enhancing = False
        self._is_asking_qa = False
        self._closing = False
        self._force_quit = False
        self._tray: Optional[QSystemTrayIcon] = None

        self._build_ui()
        self._setup_shortcuts()
        self._setup_tray()
        self._connect_signals()

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_timer)

        self._refresh_archive()
        self._refresh_tasks_and_telemetry()

        meetings = self._db.list_meetings(limit=1)
        if meetings and meetings[0].id is not None:
            self._load_meeting(meetings[0].id)
        else:
            self._create_new_meeting()

        if (
            auto_check_updates
            and self._settings.check_updates_on_startup
            and not self._settings.air_gapped_mode
        ):
            QTimer.singleShot(2500, self._check_updates_async)

    # ------------------------------------------------------------------
    # Studio 2.0 UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left Sidebar Rail (228px)
        self._sidebar = ArchiveSidebar(self._i18n)
        self._sidebar.update_privacy_status(
            self._settings.whisper_model,
            self._settings.whisper_compute_type,
            self._settings.air_gapped_mode,
        )
        root.addWidget(self._sidebar)

        # Right Stacked Views (0=Meeting Studio, 1=Tasks Hub, 2=Settings & Telemetry)
        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        self._studio_page = self._build_studio_view()
        self._tasks_view = TasksHubView(self._i18n)
        self._settings_view = SettingsView(
            self._settings, self._hw, self._tuning, self._i18n
        )

        self._stack.addWidget(self._studio_page)
        self._stack.addWidget(self._tasks_view)
        self._stack.addWidget(self._settings_view)

        # Status Bar with progress + inline cancel during import
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self._status_bar = status_bar

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFixedWidth(150)
        self._progress_bar.setVisible(False)
        status_bar.addPermanentWidget(self._progress_bar)

        self._cancel_import_btn = QPushButton(self._i18n.t("btn_cancel_import"))
        self._cancel_import_btn.setObjectName("DangerButton")
        self._cancel_import_btn.setFixedHeight(22)
        self._cancel_import_btn.setVisible(False)
        self._cancel_import_btn.clicked.connect(self._cancel_file_import)
        status_bar.addPermanentWidget(self._cancel_import_btn)

        self._set_status(self._i18n.t("status_ready"))

    def _build_studio_view(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # --- De-cluttered Studio 2.0 Command Header (2 balanced rows, zero overlap) ---
        cmd_hdr = QFrame()
        cmd_hdr.setObjectName("CommandHeader")
        hdr_v = QVBoxLayout(cmd_hdr)
        hdr_v.setContentsMargins(14, 10, 14, 9)
        hdr_v.setSpacing(7)

        # Row 1: Full-width Meeting Title + Privacy/Live Pill + Export dropdown
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self._title_input = QLineEdit()
        self._title_input.setObjectName("MeetingTitleInput")
        self._title_input.setPlaceholderText(self._i18n.t("title_placeholder"))
        self._title_input.setMinimumWidth(240)
        self._title_input.editingFinished.connect(self._on_title_edited)
        row1.addWidget(self._title_input, 1)

        self._status_pill = QLabel()
        self._status_pill.setObjectName("StatusPill")
        row1.addWidget(self._status_pill)

        self._export_btn = QPushButton(self._i18n.t("btn_export"))
        self._export_btn.setObjectName("GhostButton")
        self._export_btn.setIcon(make_flat_icon("export", "#34D399", 12))
        self._export_btn.setIconSize(QSize(12, 12))
        self._export_menu = QMenu(self)
        self._rebuild_export_menu()
        self._export_btn.setMenu(self._export_menu)
        row1.addWidget(self._export_btn)
        hdr_v.addLayout(row1)

        # Row 2: Interactive Tag Chips (Left) + Dual Waveform & Transport Controls (Right)
        row2 = QHBoxLayout()
        row2.setContentsMargins(4, 0, 0, 0)
        row2.setSpacing(6)

        self._tags_container = QHBoxLayout()
        self._tags_container.setContentsMargins(0, 0, 0, 0)
        self._tags_container.setSpacing(4)
        row2.addLayout(self._tags_container)

        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText(self._i18n.t("tag_add_ph"))
        self._tag_input.setToolTip(self._i18n.t("tag_add_tooltip"))
        self._tag_input.setFixedWidth(64)
        self._tag_input.setFixedHeight(23)
        self._tag_input.setStyleSheet(
            "QLineEdit { background-color: #141417; border: 1px dashed #2E2E38; "
            "border-radius: 10px; padding: 1px 7px; font-size: 11px; color: #D4D4D8; }"
            "QLineEdit:focus { border: 1px solid #10B981; }"
        )
        self._tag_input.returnPressed.connect(self._on_add_tag)
        row2.addWidget(self._tag_input)
        row2.addStretch(1)

        self._timer_label = QLabel("00:00")
        self._timer_label.setObjectName("TimerLabel")
        row2.addWidget(self._timer_label)

        self._level_meter = DualWaveformMeter()
        self._level_meter.setFixedSize(108, 28)
        row2.addWidget(self._level_meter)

        self._record_btn = QPushButton(self._i18n.t("btn_record"))
        self._record_btn.setObjectName("RecordButton")
        self._record_btn.setIcon(make_flat_icon("record", "#FFFFFF", 11))
        self._record_btn.setIconSize(QSize(11, 11))
        self._record_btn.setToolTip("Start / Stop live capture (Ctrl+R)")
        self._record_btn.clicked.connect(self._shortcut_toggle_record)
        row2.addWidget(self._record_btn)

        self._pause_btn = QPushButton(self._i18n.t("btn_pause"))
        self._pause_btn.setObjectName("GhostButton")
        self._pause_btn.setIcon(make_flat_icon("pause", "#E4E4E7", 11))
        self._pause_btn.setIconSize(QSize(11, 11))
        self._pause_btn.setEnabled(False)
        self._pause_btn.setToolTip("Pause / Resume recording (Ctrl+P)")
        self._pause_btn.clicked.connect(self._toggle_pause)
        row2.addWidget(self._pause_btn)

        self._import_btn = QPushButton(self._i18n.t("btn_import"))
        self._import_btn.setObjectName("GhostButton")
        self._import_btn.setIcon(make_flat_icon("import", "#A1A1AA", 12))
        self._import_btn.setIconSize(QSize(12, 12))
        self._import_btn.setToolTip("Transcribe local audio/video file (Ctrl+O or drag & drop)")
        self._import_btn.clicked.connect(self._open_import_dialog)
        row2.addWidget(self._import_btn)

        hdr_v.addLayout(row2)
        lay.addWidget(cmd_hdr)

        # Center Split: Live Transcript Stream (Left) + 4-Tab Intelligence Dock (Right)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._transcript_view = TranscriptView(self._i18n)
        self._summary_panel = SummaryPanel(self._i18n)
        splitter.addWidget(self._transcript_view)
        splitter.addWidget(self._summary_panel)
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([540, 445])
        lay.addWidget(splitter, 1)

        self._update_status_pill()
        return page

    def _rebuild_export_menu(self) -> None:
        self._export_menu.clear()
        for key, fmt in (
            ("export_md", "md"),
            ("export_obsidian", "obsidian_md"),
            ("export_srt", "srt"),
            ("export_vtt", "vtt"),
            ("export_txt", "txt"),
            ("export_json", "json"),
        ):
            act = self._export_menu.addAction(self._i18n.t(key))
            act.triggered.connect(lambda _c=False, f=fmt: self._export_current(f))
        self._export_menu.addSeparator()
        imp_json = self._export_menu.addAction(self._i18n.t("import_json_backup"))
        imp_json.triggered.connect(self._import_json_backup_dialog)

    def _update_status_pill(self) -> None:
        if self._is_recording and self._is_paused:
            self._status_pill.setText(self._i18n.t("pill_paused"))
            self._status_pill.setProperty("state", "paused")
        elif self._is_recording:
            self._status_pill.setText(self._i18n.t("pill_recording"))
            self._status_pill.setProperty("state", "recording")
        elif self._settings.air_gapped_mode:
            self._status_pill.setText(self._i18n.t("pill_airgap"))
            self._status_pill.setProperty("state", "airgap")
        else:
            self._status_pill.setText(self._i18n.t("pill_offline"))
            self._status_pill.setProperty("state", "offline")
        self._status_pill.style().unpolish(self._status_pill)
        self._status_pill.style().polish(self._status_pill)

    def _render_tag_chips(self) -> None:
        while self._tags_container.count():
            item = self._tags_container.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        tags = self._current_meeting.tags if self._current_meeting else []
        for tag in tags:
            chip = QFrame()
            chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            chip.setFixedHeight(23)
            chip.setStyleSheet(
                "QFrame { background-color: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.28); "
                "border-radius: 10px; }"
            )
            cl = QHBoxLayout(chip)
            cl.setContentsMargins(8, 1, 6, 1)
            cl.setSpacing(5)
            lbl = QLabel(f"#{tag}")
            tag_font = QFont(lbl.font())
            tag_font.setPixelSize(11)
            tag_font.setWeight(QFont.Weight.DemiBold)
            lbl.setFont(tag_font)
            lbl.setMinimumWidth(lbl.fontMetrics().horizontalAdvance(f"#{tag}") + 4)
            lbl.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            lbl.setStyleSheet("color: #6EE7B7; border: none; background: transparent;")
            cl.addWidget(lbl)

            rm = QToolButton()
            rm.setIcon(make_flat_icon("close", "#6EE7B7", 8))
            rm.setIconSize(QSize(8, 8))
            rm.setFixedSize(12, 12)
            rm.setStyleSheet("QToolButton { background: transparent; border: none; padding: 0; }")
            rm.setCursor(Qt.CursorShape.PointingHandCursor)
            rm.clicked.connect(lambda _c=False, t=tag: self._remove_tag(t))
            cl.addWidget(rm)
            self._tags_container.addWidget(chip)

    def _on_add_tag(self) -> None:
        if not self._current_meeting or self._current_meeting.id is None:
            return
        raw = self._tag_input.text().strip().lstrip("#").strip()
        self._tag_input.clear()
        if not raw or raw in self._current_meeting.tags:
            return
        self._current_meeting.tags.append(raw)
        self._db.update_meeting(self._current_meeting.id, tags=self._current_meeting.tags)
        self._render_tag_chips()

    def _remove_tag(self, tag: str) -> None:
        if not self._current_meeting or self._current_meeting.id is None:
            return
        self._current_meeting.tags = [t for t in self._current_meeting.tags if t != tag]
        self._db.update_meeting(self._current_meeting.id, tags=self._current_meeting.tags)
        self._render_tag_chips()

    # ------------------------------------------------------------------
    # Shortcuts, Tray & Signal Wiring
    # ------------------------------------------------------------------

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+R"), self, self._shortcut_toggle_record)
        QShortcut(QKeySequence("Ctrl+P"), self, self._toggle_pause)
        QShortcut(QKeySequence("Ctrl+B"), self, self._transcript_view.bookmark_latest)
        QShortcut(QKeySequence("Ctrl+N"), self, self._create_new_meeting)
        QShortcut(QKeySequence("Ctrl+O"), self, self._open_import_dialog)
        QShortcut(QKeySequence("Ctrl+F"), self, self._transcript_view.focus_search)
        QShortcut(QKeySequence("Ctrl+T"), self, self._insert_live_note_timestamp)
        QShortcut(
            QKeySequence("Ctrl+G"),
            self,
            lambda: self._start_summarization(self._summary_panel.current_template()),
        )
        QShortcut(QKeySequence("Ctrl+,"), self, lambda: self.switch_view(2))

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(create_app_icon(), self)
        tray.setToolTip(f"{__app_name__} v{__version__}")
        menu = QMenu(self)
        show_act = menu.addAction("Show LocalMinutes")
        show_act.triggered.connect(self._restore_from_tray)
        quit_act = menu.addAction("Quit")
        quit_act.triggered.connect(self._force_quit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: self._restore_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
        tray.show()
        self._tray = tray

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _force_quit_app(self) -> None:
        self._force_quit = True
        self.close()

    def _connect_signals(self) -> None:
        self._level_signal.connect(self._level_meter.set_level)
        self._segment_signal.connect(self._on_new_segment)
        self._status_signal.connect(self._set_status)
        self._error_signal.connect(self._on_async_error)
        self._summary_done_signal.connect(self._on_summary_done)
        self._summary_error_signal.connect(self._on_summary_error)
        self._enhance_done_signal.connect(self._on_enhance_done)
        self._enhance_error_signal.connect(self._on_enhance_error)
        self._qa_done_signal.connect(self._on_qa_done)
        self._import_progress_signal.connect(self._on_import_progress)
        self._import_done_signal.connect(self._on_import_done)
        self._import_error_signal.connect(self._on_import_error)
        self._benchmark_done_signal.connect(self._on_benchmark_done)

        self._sidebar.view_changed.connect(self.switch_view)
        self._sidebar.meeting_selected.connect(self._on_sidebar_selected)
        self._sidebar.new_meeting_requested.connect(self._create_new_meeting)
        self._sidebar.demo_meeting_requested.connect(self.load_demo_meeting)
        self._sidebar.delete_meeting_requested.connect(self._delete_meeting)
        self._sidebar.export_json_requested.connect(self._export_meeting_json_by_id)
        self._sidebar.search_changed.connect(self._refresh_archive)

        self._transcript_view.segment_updated.connect(self._on_segment_edited)
        self._transcript_view.segment_bookmarked.connect(self._on_segment_bookmarked)
        self._transcript_view.segment_deleted.connect(self._on_segment_deleted)
        self._transcript_view.speaker_bulk_renamed.connect(self._on_speaker_bulk_renamed)

        self._summary_panel.summarize_requested.connect(self._start_summarization)
        self._summary_panel.template_changed.connect(self._on_template_changed)
        self._summary_panel.notes_changed.connect(self._on_notes_changed)
        self._summary_panel.connect_timestamp_button(self._insert_live_note_timestamp)
        self._summary_panel.enhance_notes_requested.connect(self._start_enhance_notes)
        self._summary_panel.action_item_toggled.connect(self._on_action_item_toggled)
        self._summary_panel.action_item_added.connect(self._on_action_item_added)
        self._summary_panel.action_item_deleted.connect(self._on_action_item_deleted)
        self._summary_panel.qa_requested.connect(self._start_qa_query)
        self._summary_panel.citation_clicked.connect(self._transcript_view.scroll_to_citation)

        self._tasks_view.action_item_toggled.connect(self._on_action_item_toggled)
        self._tasks_view.action_item_deleted.connect(self._on_action_item_deleted)
        self._tasks_view.jump_to_meeting.connect(self._jump_to_meeting_from_hub)

        self._settings_view.settings_saved.connect(self._on_settings_saved)
        self._settings_view.language_changed.connect(self._on_language_changed)
        self._settings_view.check_updates_requested.connect(self._check_updates_async)
        self._settings_view.run_benchmark_requested.connect(self._run_builtin_benchmark)

    def switch_view(self, index: int) -> None:
        clamped = max(0, min(2, int(index)))
        self._stack.setCurrentIndex(clamped)
        self._sidebar.set_active_view(clamped)
        if clamped in (1, 2):
            self._refresh_tasks_and_telemetry()

    def _jump_to_meeting_from_hub(self, meeting_id: int) -> None:
        self._load_meeting(meeting_id)
        self.switch_view(0)

    # ------------------------------------------------------------------
    # Demo Meeting & JSON Backup Import
    # ------------------------------------------------------------------

    def load_demo_meeting(self) -> Meeting:
        """1-Click Load Demo Meeting: inserts realistic bilingual Sprint Planning session."""
        if self._is_recording:
            QMessageBox.information(self, "Recording Active", "Stop the active recording before loading demo.")
            assert self._current_meeting is not None
            return self._current_meeting
        self._flush_current_notes()
        demo = self._db.import_meeting_object(build_demo_meeting())
        assert demo.id is not None
        self._load_meeting(demo.id)
        self._level_meter.seed_demo_levels()
        self.switch_view(0)
        self._set_status(self._i18n.t("status_demo_loaded"))
        return demo

    def _import_json_backup_dialog(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            self._i18n.t("import_json_backup"),
            "",
            "LocalMinutes JSON Backup (*.json)",
        )
        if not path_str:
            return
        try:
            raw = Path(path_str).read_text(encoding="utf-8")
            parsed = parse_meeting_json(raw)
            self._flush_current_notes()
            saved = self._db.import_meeting_object(parsed)
            if saved.id is not None:
                self._load_meeting(saved.id)
            self._set_status(f"Imported backup: {saved.title}")
        except Exception as exc:
            QMessageBox.warning(self, "Import Backup Error", str(exc))

    # ------------------------------------------------------------------
    # Drag & Drop + Cancellable Media File Import
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData() and event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if Path(url.toLocalFile()).suffix.lower() in SUPPORTED_MEDIA_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if not event.mimeData() or not event.mimeData().hasUrls():
            return
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in SUPPORTED_MEDIA_EXTENSIONS:
                self._start_file_import(path)
                break

    def _open_import_dialog(self) -> None:
        if self._is_recording or self._is_importing:
            return
        exts = " ".join(f"*{ext}" for ext in SUPPORTED_MEDIA_EXTENSIONS)
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            self._i18n.t("btn_import"),
            "",
            f"Audio & Video Files ({exts})",
        )
        if path_str:
            self._start_file_import(Path(path_str))

    def _start_file_import(self, file_path: Path) -> None:
        if self._is_recording or self._is_importing:
            return
        self._flush_current_notes()
        self._is_importing = True
        self._import_cancel_event = threading.Event()
        self._import_btn.setEnabled(False)
        self._record_btn.setEnabled(False)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._cancel_import_btn.setVisible(True)

        meeting = self._db.create_meeting(
            title=file_path.stem,
            language=self._settings.whisper_language,
            template=self._settings.default_template,
        )
        assert meeting.id is not None
        self._importing_meeting_id = meeting.id
        self._load_meeting(meeting.id)
        self._set_status(self._i18n.t("status_importing", name=file_path.name))

        engine = self._ensure_engine()
        meeting_id = meeting.id
        cancel_ev = self._import_cancel_event

        def _worker() -> None:
            try:
                segments, duration = transcribe_media_file(
                    file_path=file_path,
                    engine=engine,
                    meeting_id=meeting_id,
                    speaker="Recording",
                    on_progress=lambda pct: self._import_progress_signal.emit(int(pct * 100)),
                    on_status=lambda msg: self._status_signal.emit(msg),
                    cancel_event=cancel_ev,
                )
                self._import_done_signal.emit(meeting_id, segments, duration, cancel_ev.is_set())
            except Exception as exc:
                self._import_error_signal.emit(str(exc))

        threading.Thread(target=_worker, daemon=True, name="FileImportWorker").start()

    def _cancel_file_import(self) -> None:
        if self._import_cancel_event is not None:
            self._import_cancel_event.set()
            self._cancel_import_btn.setEnabled(False)
            self._set_status("Cancelling import...")

    def _on_import_progress(self, pct: int) -> None:
        self._progress_bar.setValue(max(0, min(100, pct)))

    def _on_import_done(
        self, meeting_id: int, segments_obj: object, duration: float, was_cancelled: bool
    ) -> None:
        self._is_importing = False
        self._importing_meeting_id = None
        self._import_cancel_event = None
        if self._closing:
            return
        self._import_btn.setEnabled(True)
        self._record_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._cancel_import_btn.setVisible(False)
        self._cancel_import_btn.setEnabled(True)

        if isinstance(segments_obj, list) and segments_obj:
            if self._db.get_meeting(meeting_id, include_segments=False) is None:
                return
            valid = [s for s in segments_obj if isinstance(s, TranscriptSegment)]
            try:
                self._db.add_segments_bulk(valid)
                self._db.update_meeting(meeting_id, duration_sec=duration)
            except sqlite3.IntegrityError:
                return
            self._load_meeting(meeting_id)
            if was_cancelled:
                self._set_status(
                    f"{self._i18n.t('status_import_cancelled')} ({len(valid)} partial segments kept)."
                )
            else:
                self._set_status(self._i18n.t("status_import_done", count=len(valid)))
        elif was_cancelled:
            self._set_status(self._i18n.t("status_import_cancelled"))

    def _on_import_error(self, message: str) -> None:
        self._is_importing = False
        self._importing_meeting_id = None
        self._import_cancel_event = None
        if self._closing:
            return
        self._import_btn.setEnabled(True)
        self._record_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._cancel_import_btn.setVisible(False)
        self._cancel_import_btn.setEnabled(True)
        self._set_status(f"Import error: {message}")
        QMessageBox.warning(self, "Media Import Error", message)

    # ------------------------------------------------------------------
    # Archive, Meeting Switching & Notes Debounce Flush Safety
    # ------------------------------------------------------------------

    def _flush_current_notes(self) -> None:
        """Guarantee pending debounced notes are saved to the PREVIOUS meeting before switching."""
        pending = self._summary_panel.flush_pending_notes()
        if pending is not None and self._current_meeting and self._current_meeting.id is not None:
            self._current_meeting.notes = pending
            self._db.update_meeting(self._current_meeting.id, notes=pending)

    def _refresh_archive(self, query: Optional[str] = None) -> None:
        active_query = self._sidebar._search_input.text() if query is None else query
        meetings = (
            self._db.search_meetings(active_query)
            if active_query.strip()
            else self._db.list_meetings()
        )
        selected_id = self._current_meeting.id if self._current_meeting else None
        self._sidebar.set_meetings(meetings, selected_id=selected_id)

    def _refresh_tasks_and_telemetry(self) -> None:
        insights = self._db.get_archive_insights()
        all_items = self._db.list_action_items()
        self._sidebar.set_open_tasks_badge(int(insights.get("open_action_items", 0)))
        self._tasks_view.refresh_data(insights, all_items)
        self._settings_view.refresh_telemetry(insights, self._settings)

    def _on_sidebar_selected(self, meeting_id: int) -> None:
        if self._is_recording:
            QMessageBox.information(
                self,
                "Recording Active",
                "Stop the current recording before switching meetings.",
            )
            self._refresh_archive()
            return
        self._load_meeting(meeting_id)

    def _load_meeting(self, meeting_id: int) -> None:
        self._flush_current_notes()
        meeting = self._db.get_meeting(meeting_id, include_segments=True)
        if meeting is None:
            return
        self._current_meeting = meeting
        self._title_input.setText(meeting.title)
        self._timer_label.setText(format_timestamp(meeting.duration_sec))
        self._render_tag_chips()
        self._transcript_view.set_segments(meeting.segments)
        self._summary_panel.set_template(meeting.template)
        self._summary_panel.set_notes(meeting.notes)
        self._summary_panel.set_summary(meeting.summary)
        self._summary_panel.set_action_items(meeting.action_items)
        self._summary_panel.set_qa_response(None)
        self._summary_panel.update_insights(meeting.segments)
        self._refresh_archive()
        self._refresh_tasks_and_telemetry()

    def _create_new_meeting(self) -> None:
        if self._is_recording:
            QMessageBox.information(
                self,
                "Recording Active",
                "Stop the current recording before starting a new meeting.",
            )
            return
        self._flush_current_notes()
        default_title = f"Meeting — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        meeting = self._db.create_meeting(
            title=default_title,
            language=self._settings.whisper_language,
            template=self._settings.default_template,
        )
        self._current_meeting = meeting
        self._title_input.setText(meeting.title)
        self._timer_label.setText("00:00")
        self._render_tag_chips()
        self._transcript_view.clear()
        self._summary_panel.set_template(meeting.template)
        self._summary_panel.set_notes("")
        self._summary_panel.set_summary(None)
        self._summary_panel.set_action_items([])
        self._summary_panel.set_qa_response(None)
        self._summary_panel.update_insights([])
        self._level_meter.reset()
        self._refresh_archive()
        self._refresh_tasks_and_telemetry()
        self.switch_view(0)

    def _delete_meeting(self, meeting_id: int) -> None:
        if self._is_recording and self._current_meeting and self._current_meeting.id == meeting_id:
            QMessageBox.warning(self, "Recording Active", "Stop recording before deleting this meeting.")
            return
        if self._is_importing and self._importing_meeting_id == meeting_id:
            QMessageBox.warning(self, "Import Active", "Cancel or wait for the media import before deleting this meeting.")
            return
        reply = QMessageBox.question(
            self,
            self._i18n.t("archive_delete"),
            "Permanently delete this meeting, transcript, notes, and action items?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self._current_meeting and self._current_meeting.id == meeting_id:
            self._summary_panel.flush_pending_notes()  # clear pending without saving to deleted row
        self._db.delete_meeting(meeting_id)
        if self._current_meeting and self._current_meeting.id == meeting_id:
            self._current_meeting = None
            remaining = self._db.list_meetings(limit=1)
            if remaining and remaining[0].id is not None:
                self._load_meeting(remaining[0].id)
            else:
                self._create_new_meeting()
        else:
            self._refresh_archive()
            self._refresh_tasks_and_telemetry()

    def _on_title_edited(self) -> None:
        if not self._current_meeting or self._current_meeting.id is None:
            return
        new_title = self._title_input.text().strip()
        if not new_title:
            self._title_input.setText(self._current_meeting.title)
            return
        if new_title != self._current_meeting.title:
            self._current_meeting.title = new_title
            self._db.update_meeting(self._current_meeting.id, title=new_title)
            self._refresh_archive()

    def _on_template_changed(self, template_key: str) -> None:
        if not self._current_meeting or self._current_meeting.id is None:
            return
        self._current_meeting.template = template_key
        self._db.update_meeting(self._current_meeting.id, template=template_key)

    def _on_notes_changed(self, notes_text: str) -> None:
        if not self._current_meeting or self._current_meeting.id is None:
            return
        self._current_meeting.notes = notes_text
        self._db.update_meeting(self._current_meeting.id, notes=notes_text)

    def _insert_live_note_timestamp(self) -> None:
        if self._capture is not None and self._is_recording:
            sec = self._capture.elapsed_seconds
        elif self._current_meeting and self._current_meeting.segments:
            sec = self._current_meeting.segments[-1].start_sec
        else:
            sec = self._current_meeting.duration_sec if self._current_meeting else 0.0
        self._summary_panel.insert_timestamp_marker(sec)

    # ------------------------------------------------------------------
    # Segment Edits, Bulk Rename & Action Items
    # ------------------------------------------------------------------

    def _on_segment_edited(self, seg_id: int, speaker: str, text: str) -> None:
        self._db.update_segment(seg_id, speaker=speaker, text=text)
        if self._current_meeting:
            for seg in self._current_meeting.segments:
                if seg.id == seg_id:
                    seg.speaker = speaker
                    seg.text = text
                    break
            self._summary_panel.update_insights(self._current_meeting.segments)
        self._transcript_view.update_segment_local(seg_id, speaker=speaker, text=text)

    def _on_segment_bookmarked(self, seg_id: int, is_bookmarked: bool) -> None:
        self._db.update_segment(seg_id, is_bookmarked=is_bookmarked)
        if self._current_meeting:
            for seg in self._current_meeting.segments:
                if seg.id == seg_id:
                    seg.is_bookmarked = is_bookmarked
                    break
            self._summary_panel.update_insights(self._current_meeting.segments)
        self._transcript_view.update_segment_local(seg_id, is_bookmarked=is_bookmarked)

    def _on_segment_deleted(self, seg_id: int) -> None:
        self._db.delete_segment(seg_id)
        if self._current_meeting:
            self._current_meeting.segments = [
                s for s in self._current_meeting.segments if s.id != seg_id
            ]
            self._summary_panel.update_insights(self._current_meeting.segments)
        self._transcript_view.remove_segment_local(seg_id)

    def _on_speaker_bulk_renamed(self, old_speaker: str, new_speaker: str) -> None:
        if not self._current_meeting or self._current_meeting.id is None:
            return
        count = self._db.bulk_rename_speaker(self._current_meeting.id, old_speaker, new_speaker)
        if count > 0:
            for seg in self._current_meeting.segments:
                if seg.speaker == old_speaker:
                    seg.speaker = new_speaker
            self._transcript_view.set_segments(self._current_meeting.segments)
            self._summary_panel.update_insights(self._current_meeting.segments)
            self._set_status(f"Renamed {count} segments from '{old_speaker}' to '{new_speaker}'.")

    def _on_action_item_toggled(self, item_id: int, completed: bool) -> None:
        self._db.toggle_action_item(item_id, completed)
        if self._current_meeting and self._current_meeting.id is not None:
            self._current_meeting.action_items = self._db.list_action_items(
                meeting_id=self._current_meeting.id
            )
            self._summary_panel.set_action_items(self._current_meeting.action_items)
        self._refresh_tasks_and_telemetry()

    def _on_action_item_added(self, raw_text: str) -> None:
        if not self._current_meeting or self._current_meeting.id is None:
            return
        self._db.add_action_item(self._current_meeting.id, raw_text)
        self._current_meeting.action_items = self._db.list_action_items(
            meeting_id=self._current_meeting.id
        )
        self._summary_panel.set_action_items(self._current_meeting.action_items)
        self._refresh_tasks_and_telemetry()

    def _on_action_item_deleted(self, item_id: int) -> None:
        self._db.delete_action_item(item_id)
        if self._current_meeting and self._current_meeting.id is not None:
            self._current_meeting.action_items = self._db.list_action_items(
                meeting_id=self._current_meeting.id
            )
            self._summary_panel.set_action_items(self._current_meeting.action_items)
        self._refresh_tasks_and_telemetry()

    # ------------------------------------------------------------------
    # Live Recording with Continuous Resumed Timestamps
    # ------------------------------------------------------------------

    def _ensure_engine(self) -> WhisperEngine:
        if (
            self._engine is None
            or self._engine.model_size != self._settings.whisper_model
            or self._engine.compute_type != self._settings.whisper_compute_type
            or (self._engine.language or "auto") != self._settings.whisper_language
            or self._engine.initial_prompt != self._settings.custom_vocabulary.strip()
            or self._engine.local_files_only != self._settings.air_gapped_mode
            or self._engine.cpu_threads != self._tuning.whisper_threads
        ):
            self._engine = WhisperEngine(
                model_size=self._settings.whisper_model,
                compute_type=self._settings.whisper_compute_type,
                language=self._settings.whisper_language,
                initial_prompt=self._settings.custom_vocabulary,
                cpu_threads=self._tuning.whisper_threads,
                local_files_only=self._settings.air_gapped_mode,
            )
        return self._engine

    def _shortcut_toggle_record(self) -> None:
        if self._is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        if self._is_importing:
            return
        if self._current_meeting is None or self._current_meeting.id is None:
            self._create_new_meeting()
        assert self._current_meeting is not None and self._current_meeting.id is not None

        # Join any lingering flush thread from a prior stop before opening a new pipeline
        if self._pipeline_flush_thread is not None and self._pipeline_flush_thread.is_alive():
            self._pipeline_flush_thread.join(timeout=5.0)
            self._pipeline_flush_thread = None

        # Resumed recording timestamp fix: continue cleanly after existing max end_sec
        existing_max = self._db.get_meeting_max_end_sec(self._current_meeting.id)
        time_offset = (existing_max + 0.5) if existing_max > 0 else 0.0

        engine = self._ensure_engine()
        self._pipeline = LiveTranscriptionPipeline(
            engine=engine,
            on_segment=lambda seg: self._segment_signal.emit(seg),
            on_status=lambda msg: self._status_signal.emit(msg),
            on_error=lambda err: self._error_signal.emit(err),
            meeting_id=self._current_meeting.id,
            energy_threshold=self._settings.energy_threshold,
            vad_silence_ms=self._settings.vad_silence_ms,
            chunk_max_sec=self._settings.chunk_max_sec,
            time_offset_sec=0.0,  # DualAudioCapture already adds time_offset_sec
        )
        self._pipeline.start()

        wav_dir = (
            get_recordings_dir() / f"meeting_{self._current_meeting.id}"
            if self._settings.save_wav
            else None
        )

        self._capture = DualAudioCapture(
            on_audio=self._pipeline.push_audio,
            on_level=lambda spk, lvl: self._level_signal.emit(spk, lvl),
            on_error=lambda err: self._error_signal.emit(err),
            mic_device_index=self._settings.mic_device_index,
            loopback_device_index=self._settings.loopback_device_index,
            capture_mic=self._settings.capture_mic,
            capture_loopback=self._settings.capture_loopback,
            wav_dir=wav_dir,
            time_offset_sec=time_offset,
            mic_speaker="You",
            loopback_speaker="Remote",
        )

        try:
            self._capture.start()
        except Exception as exc:
            self._pipeline.stop(wait_timeout=2.0)
            self._pipeline = None
            self._capture = None
            QMessageBox.critical(self, "Audio Capture Error", str(exc))
            self._set_status(f"Error: {exc}")
            return

        self._is_recording = True
        self._is_paused = False
        self._record_btn.setText(self._i18n.t("btn_stop"))
        self._record_btn.setIcon(make_flat_icon("stop", "#FFFFFF", 11))
        self._pause_btn.setEnabled(True)
        self._pause_btn.setText(self._i18n.t("btn_pause"))
        self._import_btn.setEnabled(False)
        self._sidebar.set_recording_badge(True)
        self._update_status_pill()
        self._timer.start()

        if self._tray:
            self._tray.setToolTip(f"{__app_name__} — REC Active")
        if len(self._capture.active_channels) >= 2:
            self._set_status(self._i18n.t("status_recording_live"))
        else:
            self._set_status(self._i18n.t("status_recording_mic_only"))

    def _toggle_pause(self) -> None:
        if not self._is_recording or self._capture is None:
            return
        if self._is_paused:
            self._capture.resume()
            self._is_paused = False
            self._pause_btn.setText(self._i18n.t("btn_pause"))
            self._pause_btn.setIcon(make_flat_icon("pause", "#E4E4E7", 11))
            self._update_status_pill()
        else:
            self._capture.pause()
            self._is_paused = True
            self._pause_btn.setText(self._i18n.t("btn_resume"))
            self._pause_btn.setIcon(make_flat_icon("play", "#34D399", 11))
            self._level_meter.reset()
            self._update_status_pill()

    def _stop_recording(self, sync: bool = False) -> None:
        if not self._is_recording:
            return
        self._timer.stop()
        elapsed = self._capture.elapsed_seconds if self._capture else 0.0

        if self._capture is not None:
            self._capture.stop()
            self._capture = None

        self._level_meter.reset()
        self._set_status(self._i18n.t("status_stopping"))

        pipeline = self._pipeline
        self._pipeline = None
        if pipeline is not None:
            if sync:
                pipeline.stop(wait_timeout=10.0)
            else:
                t = threading.Thread(
                    target=self._finish_pipeline_async,
                    args=(pipeline,),
                    daemon=True,
                    name="PipelineFlush",
                )
                self._pipeline_flush_thread = t
                t.start()

        if self._current_meeting and self._current_meeting.id is not None:
            total_dur = max(self._current_meeting.duration_sec, elapsed)
            self._current_meeting.duration_sec = total_dur
            self._db.update_meeting(self._current_meeting.id, duration_sec=total_dur)
            self._timer_label.setText(format_timestamp(total_dur))

        self._is_recording = False
        self._is_paused = False
        self._record_btn.setText(self._i18n.t("btn_record"))
        self._record_btn.setIcon(make_flat_icon("record", "#FFFFFF", 11))
        self._pause_btn.setEnabled(False)
        self._pause_btn.setText(self._i18n.t("btn_pause"))
        self._import_btn.setEnabled(True)
        self._sidebar.set_recording_badge(False)
        self._update_status_pill()
        if self._tray:
            self._tray.setToolTip(f"{__app_name__} v{__version__}")
        self._refresh_archive()
        self._refresh_tasks_and_telemetry()

    def _finish_pipeline_async(self, pipeline: LiveTranscriptionPipeline) -> None:
        pipeline.stop(wait_timeout=20.0)
        self._status_signal.emit(self._i18n.t("status_stopped"))

    def _update_timer(self) -> None:
        if self._capture is not None:
            self._timer_label.setText(format_timestamp(self._capture.elapsed_seconds))

    def _on_new_segment(self, segment: TranscriptSegment) -> None:
        if self._closing or not isinstance(segment, TranscriptSegment):
            return
        if self._db.get_meeting(segment.meeting_id, include_segments=False) is None:
            return
        try:
            saved = self._db.add_segment(segment)
        except (sqlite3.IntegrityError, sqlite3.ProgrammingError):
            return
        if self._current_meeting and self._current_meeting.id == saved.meeting_id:
            self._current_meeting.segments.append(saved)
            self._transcript_view.append_segment(saved)
            self._summary_panel.update_insights(self._current_meeting.segments)

    # ------------------------------------------------------------------
    # Summarization, Enhance Notes & Ask This Meeting (Local Q&A)
    # ------------------------------------------------------------------

    def _start_summarization(self, template_key: str) -> None:
        if self._is_summarizing or not self._current_meeting or self._current_meeting.id is None:
            return
        self._flush_current_notes()
        if not self._current_meeting.segments:
            QMessageBox.information(
                self,
                "Empty Transcript",
                "Record, import, or load a demo meeting before generating a summary.",
            )
            return

        meeting_id = self._current_meeting.id
        segments_copy = list(self._current_meeting.segments)
        notes_copy = self._current_meeting.notes
        settings_copy = replace(self._settings)
        self._is_summarizing = True

        self._summary_panel.set_busy(True, "Generating summary & action items...")

        def _worker() -> None:
            try:
                result = summarize_meeting(
                    segments_copy,
                    settings_copy,
                    template=template_key,
                    notes=notes_copy,
                )
                self._summary_done_signal.emit(meeting_id, result)
            except SummarizerError as exc:
                self._summary_error_signal.emit(str(exc))
            except Exception as exc:
                self._summary_error_signal.emit(f"Unexpected summarization error: {exc}")

        threading.Thread(target=_worker, daemon=True, name="SummarizerWorker").start()

    def _on_summary_done(self, meeting_id: int, summary: object) -> None:
        self._is_summarizing = False
        if self._closing:
            return
        self._summary_panel.set_busy(False)
        if not isinstance(summary, SummaryResult):
            return
        if self._db.get_meeting(meeting_id, include_segments=False) is None:
            return
        try:
            action_items = self._db.save_summary(meeting_id, summary, sync_action_items=True)
        except (sqlite3.IntegrityError, sqlite3.ProgrammingError):
            return
        if self._current_meeting and self._current_meeting.id == meeting_id:
            self._current_meeting.summary = summary
            self._current_meeting.action_items = action_items
            self._summary_panel.set_summary(summary)
            self._summary_panel.set_action_items(action_items)
        self._refresh_archive()
        self._refresh_tasks_and_telemetry()
        self._set_status(f"Summary ready ({summary.model_used}).")

    def _on_summary_error(self, error_msg: str) -> None:
        self._is_summarizing = False
        if self._closing:
            return
        self._summary_panel.set_busy(False, "Summarization failed.")
        self._set_status(f"Summarization error: {error_msg}")
        QMessageBox.warning(self, "Summarization Error", error_msg)

    def _start_enhance_notes(self) -> None:
        if self._is_enhancing or not self._current_meeting or self._current_meeting.id is None:
            return
        self._flush_current_notes()
        if not self._current_meeting.segments:
            return
        meeting_id = self._current_meeting.id
        segs = list(self._current_meeting.segments)
        notes = self._current_meeting.notes
        settings_copy = replace(self._settings)
        self._is_enhancing = True
        self._summary_panel.set_enhance_busy(True)

        def _worker() -> None:
            try:
                enhanced, model = enhance_meeting_notes(segs, notes, settings_copy)
                self._enhance_done_signal.emit(meeting_id, enhanced, model)
            except Exception as exc:
                self._enhance_error_signal.emit(str(exc))

        threading.Thread(target=_worker, daemon=True, name="EnhanceNotesWorker").start()

    def _on_enhance_done(self, meeting_id: int, enhanced: str, model_used: str) -> None:
        self._is_enhancing = False
        if self._closing:
            return
        self._summary_panel.set_enhance_busy(False)
        if self._db.get_meeting(meeting_id, include_segments=False) is None:
            return
        try:
            self._db.update_meeting(meeting_id, notes=enhanced)
        except (sqlite3.IntegrityError, sqlite3.ProgrammingError):
            return
        if self._current_meeting and self._current_meeting.id == meeting_id:
            self._current_meeting.notes = enhanced
            self._summary_panel.apply_enhanced_notes(enhanced)
        self._set_status(f"Notes enhanced ({model_used}).")

    def _on_enhance_error(self, message: str) -> None:
        self._is_enhancing = False
        if self._closing:
            return
        self._summary_panel.set_enhance_busy(False)
        self._set_status(f"Enhance notes failed: {message}")

    def _start_qa_query(self, question: str) -> None:
        if self._is_asking_qa or not self._current_meeting or self._current_meeting.id is None:
            return
        self._flush_current_notes()
        meeting_id = self._current_meeting.id
        segs = list(self._current_meeting.segments)
        notes = self._current_meeting.notes
        settings_copy = replace(self._settings)
        self._is_asking_qa = True
        self._summary_panel.set_qa_busy(True)

        def _worker() -> None:
            res = ask_meeting(question, segs, settings_copy, notes=notes)
            self._qa_done_signal.emit(meeting_id, res)

        threading.Thread(target=_worker, daemon=True, name="AskMeetingWorker").start()

    def _on_qa_done(self, meeting_id: int, response: object) -> None:
        self._is_asking_qa = False
        if self._closing:
            return
        self._summary_panel.set_qa_busy(False)
        if isinstance(response, QAResponse) and self._current_meeting and self._current_meeting.id == meeting_id:
            self._summary_panel.set_qa_response(response)

    # ------------------------------------------------------------------
    # Export, Settings, Language, Updates & Built-in Benchmark
    # ------------------------------------------------------------------

    def _export_current(self, fmt: str) -> None:
        if not self._current_meeting:
            return
        self._flush_current_notes()
        safe_name = (
            "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "_" for ch in self._current_meeting.title).strip()
            or "meeting"
        )
        ext_map = {
            "md": ("Markdown (*.md)", ".md"),
            "obsidian_md": ("Obsidian Markdown (*.md)", ".md"),
            "txt": ("Plain Text (*.txt)", ".txt"),
            "srt": ("SubRip Subtitles (*.srt)", ".srt"),
            "vtt": ("WebVTT Subtitles (*.vtt)", ".vtt"),
            "json": ("JSON Backup (*.json)", ".json"),
        }
        filter_str, ext = ext_map[fmt]
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {ext.upper()}",
            f"{safe_name}{ext}",
            filter_str,
        )
        if not path:
            return
        try:
            saved_path = export_meeting(self._current_meeting, path, fmt)
            self._set_status(f"Exported: {saved_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    def _export_meeting_json_by_id(self, meeting_id: int) -> None:
        meeting = self._db.get_meeting(meeting_id, include_segments=True)
        if meeting is None:
            return
        safe_name = (
            "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "_" for ch in meeting.title[:40]).strip()
            or "meeting"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export JSON Backup",
            f"{safe_name}.json",
            "JSON Backup (*.json)",
        )
        if path:
            try:
                export_meeting(meeting, path, "json")
                self._set_status(f"Exported backup: {path}")
            except Exception as exc:
                QMessageBox.critical(self, "Export Error", str(exc))

    def _on_settings_saved(self, new_settings: object) -> None:
        if not isinstance(new_settings, AppSettings):
            return
        self._settings = new_settings
        self._tuning = compute_runtime_tuning(
            self._hw,
            requested_profile=self._settings.performance_profile,
            preferred_compute_type=self._settings.whisper_compute_type,
        )
        save_settings(self._settings)
        self._sidebar.update_privacy_status(
            self._settings.whisper_model,
            self._settings.whisper_compute_type,
            self._settings.air_gapped_mode,
        )
        self._update_status_pill()
        self._refresh_tasks_and_telemetry()
        self._set_status(self._i18n.t("status_saved"))

    def _on_language_changed(self, lang: str) -> None:
        self._settings.ui_language = lang
        save_settings(self._settings)
        self._i18n.set_language(lang)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Retranslate every live widget across Studio, Tasks Hub, and Settings."""
        self._sidebar.retranslate(
            self._i18n,
            self._settings.whisper_model,
            self._settings.whisper_compute_type,
            self._settings.air_gapped_mode,
        )
        self._title_input.setPlaceholderText(self._i18n.t("title_placeholder"))
        self._record_btn.setText(self._i18n.t("btn_stop" if self._is_recording else "btn_record"))
        self._pause_btn.setText(self._i18n.t("btn_resume" if self._is_paused else "btn_pause"))
        self._import_btn.setText(self._i18n.t("btn_import"))
        self._export_btn.setText(self._i18n.t("btn_export"))
        self._cancel_import_btn.setText(self._i18n.t("btn_cancel_import"))
        self._tag_input.setPlaceholderText(self._i18n.t("tag_add_ph"))
        self._rebuild_export_menu()
        self._update_status_pill()
        self._transcript_view.retranslate(self._i18n)
        self._summary_panel.retranslate(self._i18n)
        self._tasks_view.retranslate(self._i18n)
        self._settings_view.retranslate(self._i18n)

    def _check_updates_async(self) -> None:
        if self._settings.air_gapped_mode:
            msg = self._i18n.t("status_airgap_blocked_update")
            self._settings_view.set_diagnostics_text(msg)
            self._set_status(msg)
            return
        if UpdateCheckerThread is None:
            return
        self._settings_view.set_diagnostics_text(self._i18n.t("updates_checking"))
        thread = UpdateCheckerThread(current_version=__version__, parent=self)
        thread.update_checked.connect(self._on_update_checked)
        self._update_thread = thread
        thread.start()

    def _on_update_checked(self, info: object) -> None:
        if self._closing or not isinstance(info, UpdateInfo):
            return
        if info.error:
            msg = self._i18n.t("updates_error")
        elif info.is_update_available:
            msg = self._i18n.t(
                "updates_available", latest=info.latest_version, current=info.current_version
            )
        else:
            msg = self._i18n.t("updates_up_to_date", version=info.current_version)
        self._settings_view.set_diagnostics_text(msg)

    def _run_builtin_benchmark(self) -> None:
        self._settings_view.set_diagnostics_text(self._i18n.t("benchmark_running"))
        self._set_status(self._i18n.t("benchmark_running"))

        def _worker() -> None:
            # 1. Polyphase resample 1s 48 kHz stereo -> 16 kHz mono
            t = np.linspace(0.0, 1.0, 48_000, endpoint=False)
            mono = (0.5 * np.sin(2 * np.pi * 440.0 * t) * 32767).astype(np.int16)
            pcm = np.column_stack([mono, mono]).ravel().tobytes()
            t0 = time.perf_counter()
            for _ in range(10):
                resample_to_16k_mono(pcm, 2, 48_000)
            res_ms = ((time.perf_counter() - t0) / 10.0) * 1000.0

            # 2. FTS5 search over 5,000 synthetic segments
            with tempfile.TemporaryDirectory() as tmp:
                bm_db = MeetingDatabase(Path(tmp) / "bm.db")
                m = bm_db.create_meeting(title="Benchmark")
                assert m.id is not None
                segs = [
                    TranscriptSegment(
                        meeting_id=m.id,
                        speaker="You" if i % 2 == 0 else "Remote",
                        text=f"Segment {i} discussing latency optimization, PostgreSQL migration, and sprint roadmap milestone {i % 50}.",
                        start_sec=float(i * 5),
                        end_sec=float(i * 5 + 4),
                    )
                    for i in range(5000)
                ]
                bm_db.add_segments_bulk(segs)
                t1 = time.perf_counter()
                for _ in range(25):
                    bm_db.search_segments_fts("PostgreSQL migration")
                fts_ms = ((time.perf_counter() - t1) / 25.0) * 1000.0
                bm_db.close()

            # 3. Extractive summarizer on 600-segment 1-hour meeting
            hour_segs = segs[:600]
            t2 = time.perf_counter()
            extractive_summarize(hour_segs)
            sum_ms = (time.perf_counter() - t2) * 1000.0

            # 4. Offline BM25 Q&A
            t3 = time.perf_counter()
            for _ in range(20):
                retrieve_bm25_citations("PostgreSQL migration roadmap", hour_segs)
            qa_ms = ((time.perf_counter() - t3) / 20.0) * 1000.0

            self._benchmark_done_signal.emit(
                {"res_ms": res_ms, "fts_ms": fts_ms, "sum_ms": sum_ms, "qa_ms": qa_ms}
            )

        threading.Thread(target=_worker, daemon=True, name="BuiltinBenchmark").start()

    def _on_benchmark_done(self, metrics: dict) -> None:
        if self._closing:
            return
        msg = self._i18n.t(
            "benchmark_done",
            res_ms=metrics.get("res_ms", 0.0),
            fts_ms=metrics.get("fts_ms", 0.0),
            sum_ms=metrics.get("sum_ms", 0.0),
            qa_ms=metrics.get("qa_ms", 0.0),
        )
        self._settings_view.set_diagnostics_text(msg)
        self._set_status(msg)

    def _on_async_error(self, message: str) -> None:
        self._set_status(f"Notice: {message}")

    def _set_status(self, text: str) -> None:
        self._status_bar.showMessage(text)

    # ------------------------------------------------------------------
    # Clean Shutdown (Fixes closeEvent DB Race & Notes Debounce Race)
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        if (
            self._settings.minimize_to_tray
            and self._tray is not None
            and not self._force_quit
            and not self._is_recording
        ):
            event.ignore()
            self.hide()
            return

        self._flush_current_notes()

        if self._import_cancel_event is not None:
            self._import_cancel_event.set()

        if self._is_recording:
            self._stop_recording(sync=True)

        if self._pipeline_flush_thread is not None and self._pipeline_flush_thread.is_alive():
            self._pipeline_flush_thread.join(timeout=8.0)
            self._pipeline_flush_thread = None

        # Drain queued segment signals emitted during final flush BEFORE closing SQLite
        app = QApplication.instance()
        if app is not None:
            app.processEvents()

        self._closing = True

        if self._update_thread is not None and hasattr(self._update_thread, "isRunning"):
            try:
                if self._update_thread.isRunning():
                    self._update_thread.quit()
                    self._update_thread.wait(2000)
            except Exception:
                pass

        if self._tray:
            self._tray.hide()

        self._db.close()
        super().closeEvent(event)
