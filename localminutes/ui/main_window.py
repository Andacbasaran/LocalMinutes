"""Main PyQt6 Studio window for LocalMinutes v0.2."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
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
    QSplitter,
    QStatusBar,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from localminutes import __app_name__, __version__
from localminutes.audio.capture import DualAudioCapture
from localminutes.config import get_db_path, get_recordings_dir, load_settings, save_settings
from localminutes.export.exporter import export_meeting, format_timestamp
from localminutes.models import AppSettings, Meeting, SummaryResult, TranscriptSegment
from localminutes.storage.database import MeetingDatabase
from localminutes.summarization.summarizer import SummarizerError, summarize_meeting
from localminutes.transcription.engine import WhisperEngine
from localminutes.transcription.file_transcriber import (
    SUPPORTED_MEDIA_EXTENSIONS,
    transcribe_media_file,
)
from localminutes.transcription.live_pipeline import LiveTranscriptionPipeline
from localminutes.ui.widgets.level_meter import DualLevelMeter
from localminutes.ui.widgets.settings_dialog import SettingsDialog
from localminutes.ui.widgets.sidebar import ArchiveSidebar
from localminutes.ui.widgets.summary_panel import SummaryPanel
from localminutes.ui.widgets.transcript_view import TranscriptView


class MainWindow(QMainWindow):
    """LocalMinutes PyQt6 Studio main window."""

    _level_signal = pyqtSignal(str, float)
    _segment_signal = pyqtSignal(object)
    _status_signal = pyqtSignal(str)
    _error_signal = pyqtSignal(str)
    _summary_done_signal = pyqtSignal(int, object)
    _summary_error_signal = pyqtSignal(str)
    _import_progress_signal = pyqtSignal(int)
    _import_done_signal = pyqtSignal(int, object, float)
    _import_error_signal = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__} — Offline Toplantı & Ders Stüdyosu")
        self.resize(1380, 860)
        self.setAcceptDrops(True)

        self._settings: AppSettings = load_settings()
        self._db = MeetingDatabase(get_db_path())
        self._current_meeting: Optional[Meeting] = None

        self._engine: Optional[WhisperEngine] = None
        self._pipeline: Optional[LiveTranscriptionPipeline] = None
        self._capture: Optional[DualAudioCapture] = None
        self._is_recording = False
        self._is_paused = False
        self._is_importing = False
        self._tray: Optional[QSystemTrayIcon] = None

        self._build_ui()
        self._setup_shortcuts()
        self._setup_tray()
        self._connect_signals()

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_timer)

        self._refresh_archive()
        meetings = self._db.list_meetings(limit=1)
        if meetings and meetings[0].id is not None:
            self._load_meeting(meetings[0].id)
        else:
            self._create_new_meeting()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Top Studio Bar ---
        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(14, 10, 14, 10)
        top_layout.setSpacing(8)

        brand = QLabel("● LocalMinutes")
        brand.setStyleSheet("font-size: 15px; font-weight: 800; color: #60a5fa;")
        top_layout.addWidget(brand)

        self._title_input = QLineEdit()
        self._title_input.setObjectName("MeetingTitleInput")
        self._title_input.setPlaceholderText("Toplantı veya ders başlığı...")
        self._title_input.setMinimumWidth(200)
        self._title_input.editingFinished.connect(self._on_title_edited)
        top_layout.addWidget(self._title_input, 1)

        self._timer_label = QLabel("00:00")
        self._timer_label.setObjectName("TimerLabel")
        top_layout.addWidget(self._timer_label)

        self._level_meter = DualLevelMeter()
        top_layout.addWidget(self._level_meter)

        self._record_btn = QPushButton("● Kaydı Başlat")
        self._record_btn.setObjectName("RecordButton")
        self._record_btn.setToolTip("Çift kanallı canlı kaydı başlat (Ctrl+R)")
        self._record_btn.clicked.connect(self._toggle_record)
        top_layout.addWidget(self._record_btn)

        self._pause_btn = QPushButton("Duraklat")
        self._pause_btn.setEnabled(False)
        self._pause_btn.setToolTip("Kaydı duraklat / devam ettir (Ctrl+P)")
        self._pause_btn.clicked.connect(self._toggle_pause)
        top_layout.addWidget(self._pause_btn)

        self._stop_btn = QPushButton("■ Bitir")
        self._stop_btn.setObjectName("StopButton")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setToolTip("Kaydı bitir (Ctrl+R)")
        self._stop_btn.clicked.connect(self._stop_recording)
        top_layout.addWidget(self._stop_btn)

        self._import_btn = QPushButton("📂 İçe Aktar")
        self._import_btn.setObjectName("ExportButton")
        self._import_btn.setToolTip("Ses/video dosyasını offline deşifre et (Ctrl+O veya sürükle-bırak)")
        self._import_btn.clicked.connect(self._open_import_dialog)
        top_layout.addWidget(self._import_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #2b3344;")
        top_layout.addWidget(sep)

        for label, fmt in [("MD", "md"), ("TXT", "txt"), ("SRT", "srt"), ("JSON", "json")]:
            btn = QPushButton(label)
            btn.setObjectName("ExportButton")
            btn.setToolTip(f"{label} formatında dışa aktar")
            btn.clicked.connect(lambda _checked=False, f=fmt: self._export_current(f))
            top_layout.addWidget(btn)

        self._settings_btn = QPushButton("⚙ Ayarlar")
        self._settings_btn.setToolTip("Ses, Whisper modeli ve özetleme ayarları (Ctrl+,)")
        self._settings_btn.clicked.connect(self._open_settings)
        top_layout.addWidget(self._settings_btn)

        root.addWidget(top_bar)

        # --- 3-Pane Studio Workspace ---
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._sidebar = ArchiveSidebar()
        self._transcript_view = TranscriptView()
        self._summary_panel = SummaryPanel()

        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._transcript_view)
        splitter.addWidget(self._summary_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([255, 685, 440])

        root.addWidget(splitter, 1)

        # --- Status Bar with optional import progress ---
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self._status_bar = status_bar

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFixedWidth(160)
        self._progress_bar.setVisible(False)
        status_bar.addPermanentWidget(self._progress_bar)

        self._set_status("Hazır — %100 offline mod aktif. Ses/video dosyasını pencereye sürükleyip bırakabilirsiniz.")

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+R"), self, self._shortcut_toggle_record)
        QShortcut(QKeySequence("Ctrl+P"), self, self._toggle_pause)
        QShortcut(QKeySequence("Ctrl+B"), self, self._transcript_view.bookmark_latest)
        QShortcut(QKeySequence("Ctrl+N"), self, self._create_new_meeting)
        QShortcut(QKeySequence("Ctrl+O"), self, self._open_import_dialog)
        QShortcut(QKeySequence("Ctrl+F"), self, self._transcript_view.focus_search)
        QShortcut(
            QKeySequence("Ctrl+G"),
            self,
            lambda: self._start_summarization(self._summary_panel.current_template()),
        )
        QShortcut(QKeySequence("Ctrl+,"), self, self._open_settings)

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip(f"{__app_name__} — Offline Toplantı Stüdyosu")
        menu = QMenu(self)
        show_act = menu.addAction("Pencereyi Göster")
        show_act.triggered.connect(self._restore_from_tray)
        quit_act = menu.addAction("Çıkış")
        quit_act.triggered.connect(self.close)
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
        self.activateWindow()

    def _connect_signals(self) -> None:
        self._level_signal.connect(self._level_meter.set_level)
        self._segment_signal.connect(self._on_new_segment)
        self._status_signal.connect(self._set_status)
        self._error_signal.connect(self._on_async_error)
        self._summary_done_signal.connect(self._on_summary_done)
        self._summary_error_signal.connect(self._on_summary_error)
        self._import_progress_signal.connect(self._on_import_progress)
        self._import_done_signal.connect(self._on_import_done)
        self._import_error_signal.connect(self._on_import_error)

        self._sidebar.meeting_selected.connect(self._on_sidebar_selected)
        self._sidebar.new_meeting_requested.connect(self._create_new_meeting)
        self._sidebar.delete_meeting_requested.connect(self._delete_meeting)
        self._sidebar.search_changed.connect(self._on_archive_search)

        self._transcript_view.segment_updated.connect(self._on_segment_edited)
        self._transcript_view.segment_bookmarked.connect(self._on_segment_bookmarked)
        self._transcript_view.segment_deleted.connect(self._on_segment_deleted)

        self._summary_panel.summarize_requested.connect(self._start_summarization)
        self._summary_panel.template_changed.connect(self._on_template_changed)
        self._summary_panel.notes_changed.connect(self._on_notes_changed)

    # ------------------------------------------------------------------
    # Drag & Drop Media Import
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
            QMessageBox.information(
                self,
                "İşlem Devam Ediyor",
                "Dosya içe aktarmak için önce mevcut kayıt veya aktarım işleminin bitmesini bekleyin.",
            )
            return
        exts = " ".join(f"*{ext}" for ext in SUPPORTED_MEDIA_EXTENSIONS)
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Ses veya Video Dosyası Seç",
            "",
            f"Ses & Video Dosyaları ({exts})",
        )
        if path_str:
            self._start_file_import(Path(path_str))

    def _start_file_import(self, file_path: Path) -> None:
        if self._is_recording or self._is_importing:
            return
        self._is_importing = True
        self._import_btn.setEnabled(False)
        self._record_btn.setEnabled(False)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)

        meeting = self._db.create_meeting(
            title=file_path.stem,
            language=self._settings.whisper_language,
            template=self._settings.default_template,
        )
        assert meeting.id is not None
        self._current_meeting = meeting
        self._load_meeting(meeting.id)
        self._set_status(f"Dosya deşifre ediliyor: {file_path.name}...")

        engine = self._ensure_engine()
        meeting_id = meeting.id

        def _worker() -> None:
            try:
                segments, duration = transcribe_media_file(
                    file_path=file_path,
                    engine=engine,
                    meeting_id=meeting_id,
                    speaker="Kayıt",
                    on_progress=lambda pct: self._import_progress_signal.emit(int(pct * 100)),
                    on_status=lambda msg: self._status_signal.emit(msg),
                )
                self._import_done_signal.emit(meeting_id, segments, duration)
            except Exception as exc:
                self._import_error_signal.emit(str(exc))

        threading.Thread(target=_worker, daemon=True, name="FileImportWorker").start()

    def _on_import_progress(self, pct: int) -> None:
        self._progress_bar.setValue(max(0, min(100, pct)))

    def _on_import_done(self, meeting_id: int, segments_obj: object, duration: float) -> None:
        self._is_importing = False
        self._import_btn.setEnabled(True)
        self._record_btn.setEnabled(True)
        self._progress_bar.setVisible(False)

        if isinstance(segments_obj, list):
            for seg in segments_obj:
                if isinstance(seg, TranscriptSegment):
                    self._db.add_segment(seg)
            self._db.update_meeting(meeting_id, duration_sec=duration)
            self._load_meeting(meeting_id)
            self._set_status(
                f"Dosya deşifresi tamamlandı ({len(segments_obj)} satır). '✦ Özetle' ile özet çıkarabilirsiniz."
            )

    def _on_import_error(self, message: str) -> None:
        self._is_importing = False
        self._import_btn.setEnabled(True)
        self._record_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._set_status(f"İçe aktarma hatası: {message}")
        QMessageBox.warning(self, "Dosya İçe Aktarma Hatası", message)

    # ------------------------------------------------------------------
    # Archive & Meeting Management
    # ------------------------------------------------------------------

    def _refresh_archive(self, query: str = "") -> None:
        meetings = self._db.search_meetings(query) if query.strip() else self._db.list_meetings()
        selected_id = self._current_meeting.id if self._current_meeting else None
        self._sidebar.set_meetings(meetings, selected_id=selected_id)

    def _on_archive_search(self, query: str) -> None:
        self._refresh_archive(query)

    def _on_sidebar_selected(self, meeting_id: int) -> None:
        if self._is_recording:
            QMessageBox.information(
                self,
                "Kayıt Devam Ediyor",
                "Başka bir toplantıya geçmeden önce mevcut kaydı durdurun.",
            )
            self._refresh_archive()
            return
        self._load_meeting(meeting_id)

    def _load_meeting(self, meeting_id: int) -> None:
        meeting = self._db.get_meeting(meeting_id, include_segments=True)
        if meeting is None:
            return
        self._current_meeting = meeting
        self._title_input.setText(meeting.title)
        self._timer_label.setText(format_timestamp(meeting.duration_sec))
        self._transcript_view.set_segments(meeting.segments)
        self._summary_panel.set_template(meeting.template)
        self._summary_panel.set_notes(meeting.notes)
        self._summary_panel.set_summary(meeting.summary)
        self._refresh_archive()

    def _create_new_meeting(self) -> None:
        if self._is_recording:
            QMessageBox.information(
                self,
                "Kayıt Devam Ediyor",
                "Yeni toplantı oluşturmak için önce mevcut kaydı bitirin.",
            )
            return
        default_title = f"Toplantı — {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        meeting = self._db.create_meeting(
            title=default_title,
            language=self._settings.whisper_language,
            template=self._settings.default_template,
        )
        self._current_meeting = meeting
        self._title_input.setText(meeting.title)
        self._timer_label.setText("00:00")
        self._transcript_view.clear()
        self._summary_panel.set_template(meeting.template)
        self._summary_panel.set_notes("")
        self._summary_panel.set_summary(None)
        self._refresh_archive()
        self._set_status("Yeni toplantı oturumu hazır.")

    def _delete_meeting(self, meeting_id: int) -> None:
        if self._is_recording and self._current_meeting and self._current_meeting.id == meeting_id:
            QMessageBox.warning(self, "Kayıt Aktif", "Aktif kayıt silinemez. Önce kaydı durdurun.")
            return
        reply = QMessageBox.question(
            self,
            "Toplantıyı Sil",
            "Bu toplantı kaydı ve transkripti kalıcı olarak silinsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
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

    # ------------------------------------------------------------------
    # Segment Interactive Edits & Bookmarks
    # ------------------------------------------------------------------

    def _on_segment_edited(self, seg_id: int, speaker: str, text: str) -> None:
        self._db.update_segment(seg_id, speaker=speaker, text=text)
        if self._current_meeting:
            for seg in self._current_meeting.segments:
                if seg.id == seg_id:
                    seg.speaker = speaker
                    seg.text = text
                    break
        self._transcript_view.update_segment_local(seg_id, speaker=speaker, text=text)
        self._set_status("Transkript satırı güncellendi.")

    def _on_segment_bookmarked(self, seg_id: int, is_bookmarked: bool) -> None:
        self._db.update_segment(seg_id, is_bookmarked=is_bookmarked)
        if self._current_meeting:
            for seg in self._current_meeting.segments:
                if seg.id == seg_id:
                    seg.is_bookmarked = is_bookmarked
                    break
        self._transcript_view.update_segment_local(seg_id, is_bookmarked=is_bookmarked)
        self._set_status("Önemli an işaretlendi ★" if is_bookmarked else "İşaret kaldırıldı.")

    def _on_segment_deleted(self, seg_id: int) -> None:
        self._db.delete_segment(seg_id)
        if self._current_meeting:
            self._current_meeting.segments = [
                s for s in self._current_meeting.segments if s.id != seg_id
            ]
        self._transcript_view.remove_segment_local(seg_id)
        self._set_status("Transkript satırı silindi.")

    # ------------------------------------------------------------------
    # Recording & Live Transcription
    # ------------------------------------------------------------------

    def _ensure_engine(self) -> WhisperEngine:
        if (
            self._engine is None
            or self._engine.model_size != self._settings.whisper_model
            or self._engine.compute_type != self._settings.whisper_compute_type
            or (self._engine.language or "auto") != self._settings.whisper_language
        ):
            self._engine = WhisperEngine(
                model_size=self._settings.whisper_model,
                compute_type=self._settings.whisper_compute_type,
                language=self._settings.whisper_language,
            )
        return self._engine

    def _shortcut_toggle_record(self) -> None:
        if self._is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _toggle_record(self) -> None:
        if not self._is_recording:
            self._start_recording()

    def _start_recording(self) -> None:
        if self._is_importing:
            return
        if self._current_meeting is None or self._current_meeting.id is None:
            self._create_new_meeting()
        assert self._current_meeting is not None and self._current_meeting.id is not None

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
        )

        try:
            self._capture.start()
        except Exception as exc:
            self._pipeline.stop(wait_timeout=2.0)
            self._pipeline = None
            self._capture = None
            QMessageBox.critical(self, "Ses Başlatma Hatası", str(exc))
            self._set_status(f"Hata: {exc}")
            return

        self._is_recording = True
        self._is_paused = False
        self._record_btn.setEnabled(False)
        self._record_btn.setText("● Kaydediliyor")
        self._pause_btn.setEnabled(True)
        self._pause_btn.setText("Duraklat")
        self._stop_btn.setEnabled(True)
        self._import_btn.setEnabled(False)
        self._settings_btn.setEnabled(False)
        self._timer.start()
        if self._tray:
            self._tray.setToolTip(f"{__app_name__} — ● Kayıt Devam Ediyor")
        self._set_status("Çift kanallı kayıt aktif (Mikrofon + WASAPI Loopback)...")

    def _toggle_pause(self) -> None:
        if not self._is_recording or self._capture is None:
            return
        if self._is_paused:
            self._capture.resume()
            self._is_paused = False
            self._pause_btn.setText("Duraklat")
            self._set_status("Kayıt devam ediyor...")
        else:
            self._capture.pause()
            self._is_paused = True
            self._pause_btn.setText("Devam Et")
            self._level_meter.reset()
            self._set_status("Kayıt duraklatıldı.")

    def _stop_recording(self) -> None:
        if not self._is_recording:
            return
        self._timer.stop()
        elapsed = self._capture.elapsed_seconds if self._capture else 0.0

        if self._capture is not None:
            self._capture.stop()
            self._capture = None

        self._level_meter.reset()
        self._set_status("Son konuşma parçaları deşifre ediliyor...")

        pipeline = self._pipeline
        self._pipeline = None
        if pipeline is not None:
            threading.Thread(
                target=self._finish_pipeline_async,
                args=(pipeline,),
                daemon=True,
            ).start()

        if self._current_meeting and self._current_meeting.id is not None:
            total_dur = max(self._current_meeting.duration_sec, elapsed)
            self._current_meeting.duration_sec = total_dur
            self._db.update_meeting(self._current_meeting.id, duration_sec=total_dur)
            self._timer_label.setText(format_timestamp(total_dur))

        self._is_recording = False
        self._is_paused = False
        self._record_btn.setEnabled(True)
        self._record_btn.setText("● Kaydı Başlat")
        self._pause_btn.setEnabled(False)
        self._pause_btn.setText("Duraklat")
        self._stop_btn.setEnabled(False)
        self._import_btn.setEnabled(True)
        self._settings_btn.setEnabled(True)
        if self._tray:
            self._tray.setToolTip(f"{__app_name__} — Hazır")
        self._refresh_archive()

    def _finish_pipeline_async(self, pipeline: LiveTranscriptionPipeline) -> None:
        pipeline.stop(wait_timeout=20.0)
        self._status_signal.emit("Kayıt tamamlandı. Dilerseniz '✦ Özetle' (Ctrl+G) ile özet çıkarabilirsiniz.")

    def _update_timer(self) -> None:
        if self._capture is not None:
            self._timer_label.setText(format_timestamp(self._capture.elapsed_seconds))

    def _on_new_segment(self, segment: TranscriptSegment) -> None:
        if not isinstance(segment, TranscriptSegment):
            return
        saved = self._db.add_segment(segment)
        if self._current_meeting and self._current_meeting.id == saved.meeting_id:
            self._current_meeting.segments.append(saved)
            self._transcript_view.append_segment(saved)

    # ------------------------------------------------------------------
    # Summarization
    # ------------------------------------------------------------------

    def _start_summarization(self, template_key: str) -> None:
        if not self._current_meeting or self._current_meeting.id is None:
            return
        if not self._current_meeting.segments:
            QMessageBox.information(
                self,
                "Transkript Boş",
                "Özet oluşturmak için önce en az bir transkript satırı olmalıdır.",
            )
            return

        meeting_id = self._current_meeting.id
        segments_copy = list(self._current_meeting.segments)
        notes_copy = self._current_meeting.notes
        settings_copy = self._settings

        provider_labels = {
            "auto": f"Otomatik (Ollama {settings_copy.ollama_model} / Yerleşik)",
            "ollama": f"Ollama ({settings_copy.ollama_model})",
            "local_extractive": "Yerleşik Offline Motor",
            "openai_compatible": f"API ({settings_copy.api_model})",
        }
        provider_label = provider_labels.get(settings_copy.llm_provider, settings_copy.llm_provider)
        self._summary_panel.set_busy(True, f"{provider_label} ile özet oluşturuluyor...")
        self._set_status(f"Özet oluşturuluyor ({provider_label})...")

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
                self._summary_error_signal.emit(f"Beklenmeyen özetleme hatası: {exc}")

        threading.Thread(target=_worker, daemon=True, name="SummarizerWorker").start()

    def _on_summary_done(self, meeting_id: int, summary: object) -> None:
        self._summary_panel.set_busy(False)
        if not isinstance(summary, SummaryResult):
            return
        self._db.save_summary(meeting_id, summary)
        if self._current_meeting and self._current_meeting.id == meeting_id:
            self._current_meeting.summary = summary
            self._summary_panel.set_summary(summary)
        self._refresh_archive()
        self._set_status(f"Özet oluşturuldu ({summary.model_used}).")

    def _on_summary_error(self, error_msg: str) -> None:
        self._summary_panel.set_busy(False, "Özetleme başarısız.")
        self._set_status(f"Özetleme hatası: {error_msg}")
        QMessageBox.warning(self, "Özetleme Hatası", error_msg)

    # ------------------------------------------------------------------
    # Export & Settings
    # ------------------------------------------------------------------

    def _export_current(self, fmt: str) -> None:
        if not self._current_meeting:
            return
        safe_name = "".join(
            ch if ch.isalnum() or ch in (" ", "-", "_") else "_" for ch in self._current_meeting.title
        ).strip() or "toplanti"
        ext_map = {
            "md": ("Markdown Dosyası (*.md)", ".md"),
            "txt": ("Metin Dosyası (*.txt)", ".txt"),
            "srt": ("Altyazı Dosyası (*.srt)", ".srt"),
            "json": ("JSON Yedek Dosyası (*.json)", ".json"),
        }
        filter_str, ext = ext_map[fmt]
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"{fmt.upper()} Olarak Dışa Aktar",
            f"{safe_name}{ext}",
            filter_str,
        )
        if not path:
            return
        try:
            saved_path = export_meeting(self._current_meeting, path, fmt)
            self._set_status(f"Dışa aktarıldı: {saved_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Dışa Aktarma Hatası", str(exc))

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._settings, parent=self)
        if dialog.exec():
            self._settings = dialog.get_settings()
            save_settings(self._settings)
            self._set_status("Ayarlar kaydedildi.")

    def _on_async_error(self, message: str) -> None:
        self._set_status(f"Uyarı: {message}")

    def _set_status(self, text: str) -> None:
        self._status_bar.showMessage(text)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._is_recording:
            self._stop_recording()
        if self._tray:
            self._tray.hide()
        self._db.close()
        super().closeEvent(event)
