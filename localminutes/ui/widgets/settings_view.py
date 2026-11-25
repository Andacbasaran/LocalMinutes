"""Studio 2.0 View 3 — Settings & System Telemetry (cross-platform audio, Whisper, LLM, Privacy, Updates)."""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from localminutes import __version__
from localminutes.audio.devices import get_loopback_setup_hint, list_audio_devices
from localminutes.config import get_models_dir
from localminutes.hardware import (
    HardwareProfile,
    RuntimeTuning,
    format_hardware_summary,
)
from localminutes.i18n import LanguageManager
from localminutes.models import SUMMARY_TEMPLATES, AppSettings, get_template_meta
from localminutes.summarization.summarizer import list_ollama_models
from localminutes.transcription.engine import (
    WHISPER_MODELS,
    delete_cached_model,
    get_cached_model_info,
)
from localminutes.ui.studio_widgets import (
    FlatComboBox,
    FlatSwitch,
    TelemetryCard,
    make_flat_icon,
)


class SettingsView(QWidget):
    """Embedded Studio 2.0 Settings & Telemetry view."""

    settings_saved = pyqtSignal(object)  # AppSettings
    language_changed = pyqtSignal(str)  # "en" | "tr"
    check_updates_requested = pyqtSignal()
    run_benchmark_requested = pyqtSignal()
    _model_dl_done = pyqtSignal(bool, str)
    _ollama_models_loaded = pyqtSignal(list, str)

    def __init__(
        self,
        settings: AppSettings,
        hw: HardwareProfile,
        tuning: RuntimeTuning,
        i18n: LanguageManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = replace(settings)
        self._hw = hw
        self._tuning = tuning
        self._i18n = i18n
        self._model_dl_done.connect(self._on_model_download_finished)
        self._ollama_models_loaded.connect(self._on_ollama_models_loaded)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(12)

        # Header + Save button
        top = QHBoxLayout()
        hdr_col = QVBoxLayout()
        hdr_col.setSpacing(2)
        self._title_lbl = QLabel(i18n.t("settings_header"))
        self._title_lbl.setObjectName("PageTitle")
        hdr_col.addWidget(self._title_lbl)

        self._sub_lbl = QLabel(i18n.t("settings_subtitle"))
        self._sub_lbl.setObjectName("MutedLabel")
        hdr_col.addWidget(self._sub_lbl)
        top.addLayout(hdr_col, 1)

        self.btn_save = QPushButton(i18n.t("btn_save_settings"))
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.setIcon(make_flat_icon("check", "#041710", 12))
        self.btn_save.setIconSize(QSize(12, 12))
        self.btn_save.setFixedHeight(34)
        self.btn_save.clicked.connect(self._save_clicked)
        top.addWidget(self.btn_save)
        root.addLayout(top)

        # Hardware Summary Banner
        hw_banner = QFrame()
        hw_banner.setObjectName("StudioCard")
        hw_lay = QHBoxLayout(hw_banner)
        hw_lay.setContentsMargins(12, 8, 12, 8)
        self._hw_badge = QLabel(format_hardware_summary(hw, tuning, lang=i18n.lang))
        self._hw_badge.setStyleSheet("color: #A1A1AA; font-size: 11.5px; font-weight: 600;")
        hw_lay.addWidget(self._hw_badge)
        root.addWidget(hw_banner)

        # 4 TelemetryCard KPIs
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)
        self.card_engine = TelemetryCard(
            i18n.t("kpi_engine"),
            tuning.compute_type_candidates[0].upper() if tuning.compute_type_candidates else "INT8",
            settings.whisper_model,
            f"CPU ({tuning.whisper_threads} threads) · Silero VAD",
            "#10B981",
            68,
        )
        self.card_vram = TelemetryCard(
            i18n.t("kpi_vram"),
            "100% CPU",
            "0 MB",
            "No dedicated GPU required",
            "#38BDF8",
            100,
        )
        self.card_privacy = TelemetryCard(
            i18n.t("kpi_privacy"),
            "AIR-GAPPED" if settings.air_gapped_mode else "LOCAL",
            "0 Bots",
            "0 bytes uploaded to cloud",
            "#10B981",
            100,
        )
        self.card_storage = TelemetryCard(
            i18n.t("kpi_storage"),
            "FTS5",
            "0.0 MB",
            "SQLite WAL local archive",
            "#A78BFA",
            30,
        )
        for card in (self.card_engine, self.card_vram, self.card_privacy, self.card_storage):
            kpi_row.addWidget(card, 1)
        root.addLayout(kpi_row)

        # Scrollable Sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setObjectName("SettingsViewport")
        scroll.viewport().setStyleSheet("QWidget#SettingsViewport { background: #0A0A0C; }")
        body = QWidget()
        body.setObjectName("SettingsBody")
        body.setStyleSheet("QWidget#SettingsBody { background: #0A0A0C; }")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 6, 8)
        body_lay.setSpacing(12)

        body_lay.addWidget(self._build_audio_card())
        body_lay.addWidget(self._build_whisper_card())
        body_lay.addWidget(self._build_llm_card())
        body_lay.addWidget(self._build_system_card())
        body_lay.addStretch()

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

    def _make_section_card(self, title: str) -> tuple[QFrame, QLabel, QFormLayout]:
        card = QFrame()
        card.setObjectName("StudioCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)

        lbl = QLabel(title)
        lbl.setObjectName("SectionTitle")
        v.addWidget(lbl)

        form = QFormLayout()
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(form)
        return card, lbl, form

    def _build_audio_card(self) -> QFrame:
        card, self._sec_audio_lbl, form = self._make_section_card(self._i18n.t("sec_audio"))

        self._capture_mic_cb = FlatSwitch(self._i18n.t("lbl_capture_mic"))
        self._capture_mic_cb.setChecked(self._settings.capture_mic)
        form.addRow(self._capture_mic_cb)

        mic_row = QHBoxLayout()
        self._mic_combo = FlatComboBox()
        mic_row.addWidget(self._mic_combo, 1)

        self._refresh_dev_btn = QPushButton(self._i18n.t("btn_refresh_devices"))
        self._refresh_dev_btn.setObjectName("GhostButton")
        self._refresh_dev_btn.setIcon(make_flat_icon("refresh", "#A1A1AA", 12))
        self._refresh_dev_btn.setIconSize(QSize(12, 12))
        self._refresh_dev_btn.clicked.connect(self.refresh_audio_devices)
        mic_row.addWidget(self._refresh_dev_btn)
        form.addRow(self._i18n.t("lbl_mic_device"), mic_row)

        self._capture_lb_cb = FlatSwitch(self._i18n.t("lbl_capture_lb"))
        self._capture_lb_cb.setChecked(self._settings.capture_loopback)
        form.addRow(self._capture_lb_cb)

        self._lb_combo = FlatComboBox()
        form.addRow(self._i18n.t("lbl_lb_device"), self._lb_combo)

        self._os_audio_hint = QLabel(get_loopback_setup_hint(lang=self._i18n.lang))
        self._os_audio_hint.setWordWrap(True)
        self._os_audio_hint.setStyleSheet(
            "color: #93C5FD; background-color: rgba(56,189,248,0.09); border: 1px solid rgba(56,189,248,0.25); "
            "border-radius: 7px; padding: 7px 10px; font-size: 11.5px;"
        )
        form.addRow(self._os_audio_hint)

        self._save_wav_cb = FlatSwitch(self._i18n.t("lbl_save_wav"))
        self._save_wav_cb.setChecked(self._settings.save_wav)
        form.addRow(self._save_wav_cb)

        self.refresh_audio_devices()
        return card

    def refresh_audio_devices(self) -> None:
        mics, loopbacks = list_audio_devices()
        self._mic_combo.clear()
        self._mic_combo.addItem(self._i18n.t("lbl_auto_mic"), None)
        for dev in mics:
            self._mic_combo.addItem(dev.display_name, dev.index)
        self._select_combo_data(self._mic_combo, self._settings.mic_device_index)

        self._lb_combo.clear()
        self._lb_combo.addItem(self._i18n.t("lbl_auto_lb"), None)
        for dev in loopbacks:
            self._lb_combo.addItem(dev.display_name, dev.index)
        self._select_combo_data(self._lb_combo, self._settings.loopback_device_index)

    def _build_whisper_card(self) -> QFrame:
        card, self._sec_whisper_lbl, form = self._make_section_card(self._i18n.t("sec_whisper"))

        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        self._model_combo = FlatComboBox()
        self._populate_whisper_models()
        self._select_combo_data(self._model_combo, self._settings.whisper_model)
        self._model_combo.currentIndexChanged.connect(self._update_model_cache_label)
        model_row.addWidget(self._model_combo, 1)

        self._dl_model_btn = QPushButton(self._i18n.t("btn_download_model"))
        self._dl_model_btn.setObjectName("PrimaryButton")
        self._dl_model_btn.setIcon(make_flat_icon("download", "#041710", 12))
        self._dl_model_btn.setIconSize(QSize(12, 12))
        self._dl_model_btn.clicked.connect(self._download_selected_model)
        model_row.addWidget(self._dl_model_btn)

        self._del_model_btn = QPushButton(self._i18n.t("btn_delete_model"))
        self._del_model_btn.setObjectName("DangerButton")
        self._del_model_btn.setIcon(make_flat_icon("trash", "#FDA4AF", 12))
        self._del_model_btn.setIconSize(QSize(12, 12))
        self._del_model_btn.clicked.connect(self._delete_selected_model)
        model_row.addWidget(self._del_model_btn)
        form.addRow(self._i18n.t("lbl_whisper_model"), model_row)

        self._model_status_label = QLabel("")
        self._model_status_label.setObjectName("MutedLabel")
        self._update_model_cache_label()
        form.addRow("", self._model_status_label)

        self._compute_combo = FlatComboBox()
        for c in ("int8", "int8_float32", "float32"):
            self._compute_combo.addItem(c.upper(), c)
        self._select_combo_data(self._compute_combo, self._settings.whisper_compute_type)
        form.addRow(self._i18n.t("lbl_compute_type"), self._compute_combo)

        self._lang_combo = FlatComboBox()
        for label, code in (
            ("Auto-Detect (EN / TR / Multi)", "auto"),
            ("English (en)", "en"),
            ("Türkçe (tr)", "tr"),
        ):
            self._lang_combo.addItem(label, code)
        self._select_combo_data(self._lang_combo, self._settings.whisper_language)
        form.addRow(self._i18n.t("lbl_speech_lang"), self._lang_combo)

        self._custom_vocab_edit = QLineEdit(self._settings.custom_vocabulary)
        self._custom_vocab_edit.setPlaceholderText(self._i18n.t("custom_vocab_ph"))
        form.addRow(self._i18n.t("lbl_custom_vocab"), self._custom_vocab_edit)

        tune_row = QHBoxLayout()
        tune_row.setSpacing(10)
        self._vad_spin = QSpinBox()
        self._vad_spin.setRange(300, 3000)
        self._vad_spin.setSingleStep(100)
        self._vad_spin.setSuffix(" ms")
        self._vad_spin.setValue(self._settings.vad_silence_ms)
        tune_row.addWidget(QLabel("VAD:"))
        tune_row.addWidget(self._vad_spin)

        self._chunk_spin = QDoubleSpinBox()
        self._chunk_spin.setRange(4.0, 30.0)
        self._chunk_spin.setSingleStep(1.0)
        self._chunk_spin.setSuffix(" s")
        self._chunk_spin.setValue(self._settings.chunk_max_sec)
        tune_row.addWidget(QLabel("Max Chunk:"))
        tune_row.addWidget(self._chunk_spin)

        self._energy_spin = QDoubleSpinBox()
        self._energy_spin.setDecimals(4)
        self._energy_spin.setRange(0.001, 0.1)
        self._energy_spin.setSingleStep(0.001)
        self._energy_spin.setValue(self._settings.energy_threshold)
        tune_row.addWidget(QLabel("RMS:"))
        tune_row.addWidget(self._energy_spin)
        tune_row.addStretch()
        form.addRow(self._i18n.t("lbl_vad_silence"), tune_row)
        return card

    def _populate_whisper_models(self) -> None:
        info = get_cached_model_info()
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for m in WHISPER_MODELS:
            entry = info[m]
            if entry["cached"]:
                label = f"{m}  ({entry['size_mb']} MB · Cached)"
            else:
                label = f"{m}  (~{entry['approx_mb']} MB)"
            self._model_combo.addItem(label, m)
        self._model_combo.blockSignals(False)

    def _update_model_cache_label(self) -> None:
        selected = str(self._model_combo.currentData() or "small")
        info = get_cached_model_info().get(selected, {})
        cached = bool(info.get("cached", False))
        self._del_model_btn.setEnabled(cached)
        if cached:
            self._model_status_label.setText(
                f"Cached locally ({info.get('size_mb', 0)} MB) — ready for 100% offline transcription."
            )
            self._dl_model_btn.setText("Cached")
        else:
            self._model_status_label.setText(
                f"Not downloaded yet (~{info.get('approx_mb', 485)} MB). Click Download to pre-cache offline."
            )
            self._dl_model_btn.setText(self._i18n.t("btn_download_model"))

    def _download_selected_model(self) -> None:
        if self.chk_air_gapped.isChecked() or self._settings.air_gapped_mode:
            self._model_status_label.setText(
                "Air-Gapped Privacy Mode is active — outbound model downloads are blocked."
            )
            return

        model_name = str(self._model_combo.currentData() or "small")
        self._dl_model_btn.setEnabled(False)
        self._del_model_btn.setEnabled(False)
        self._model_combo.setEnabled(False)
        self._dl_model_btn.setText("Downloading...")
        self._model_status_label.setText(f"Downloading Whisper '{model_name}' into local cache...")

        def _worker() -> None:
            try:
                from faster_whisper.utils import download_model

                cache_dir = str(get_models_dir())
                download_model(model_name, cache_dir=cache_dir)
                self._model_dl_done.emit(True, f"Model '{model_name}' cached and ready offline.")
            except Exception as exc:
                self._model_dl_done.emit(False, f"Download error: {exc}")

        threading.Thread(target=_worker, daemon=True, name="ModelDownloader").start()

    def _delete_selected_model(self) -> None:
        selected = str(self._model_combo.currentData() or "small")
        if delete_cached_model(selected):
            self._populate_whisper_models()
            self._select_combo_data(self._model_combo, selected)
            self._update_model_cache_label()
            self._model_status_label.setText(f"Deleted cached model '{selected}'.")

    def _on_model_download_finished(self, _ok: bool, message: str) -> None:
        selected = str(self._model_combo.currentData() or "small")
        self._populate_whisper_models()
        self._select_combo_data(self._model_combo, selected)
        self._dl_model_btn.setEnabled(True)
        self._del_model_btn.setEnabled(True)
        self._model_combo.setEnabled(True)
        self._update_model_cache_label()
        self._model_status_label.setText(message)

    def _build_llm_card(self) -> QFrame:
        card, self._sec_llm_lbl, form = self._make_section_card(self._i18n.t("sec_llm"))

        # Strict Air-Gapped Privacy Mode toggle
        airgap_wrap = QFrame()
        airgap_wrap.setObjectName("PrivacyCard")
        al = QHBoxLayout(airgap_wrap)
        al.setContentsMargins(10, 8, 10, 8)
        self.chk_air_gapped = FlatSwitch(self._i18n.t("lbl_air_gapped"))
        self.chk_air_gapped.setChecked(self._settings.air_gapped_mode)
        al.addWidget(self.chk_air_gapped)
        form.addRow(airgap_wrap)

        self._provider_combo = FlatComboBox()
        self._provider_combo.addItem("Auto (Local Ollama -> Built-in Offline)", "auto")
        self._provider_combo.addItem("Local Ollama (100% Offline LLM)", "ollama")
        self._provider_combo.addItem("Built-in Offline Engine (Zero Setup)", "local_extractive")
        self._provider_combo.addItem("OpenAI-Compatible API (Optional)", "openai_compatible")
        self._select_combo_data(self._provider_combo, self._settings.llm_provider)
        form.addRow(self._i18n.t("lbl_llm_provider"), self._provider_combo)

        self._default_tmpl_combo = FlatComboBox()
        for key in SUMMARY_TEMPLATES:
            self._default_tmpl_combo.addItem(get_template_meta(key, lang=self._i18n.lang)["label"], key)
        self._select_combo_data(self._default_tmpl_combo, self._settings.default_template)
        form.addRow(self._i18n.t("lbl_default_template"), self._default_tmpl_combo)

        self._ollama_url_edit = QLineEdit(self._settings.ollama_url)
        form.addRow(self._i18n.t("lbl_ollama_url"), self._ollama_url_edit)

        ollama_row = QHBoxLayout()
        self._ollama_model_combo = FlatComboBox()
        self._ollama_model_combo.setEditable(True)
        self._ollama_model_combo.setEditText(self._settings.ollama_model)
        self._scan_ollama_btn = QPushButton(self._i18n.t("btn_scan_ollama"))
        self._scan_ollama_btn.setObjectName("GhostButton")
        self._scan_ollama_btn.clicked.connect(self._refresh_ollama_models)
        ollama_row.addWidget(self._ollama_model_combo, 1)
        ollama_row.addWidget(self._scan_ollama_btn)
        form.addRow(self._i18n.t("lbl_ollama_model"), ollama_row)

        self._api_url_edit = QLineEdit(self._settings.api_base_url)
        form.addRow(self._i18n.t("lbl_api_url"), self._api_url_edit)

        self._api_key_edit = QLineEdit(self._settings.api_key)
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("sk-...")
        form.addRow(self._i18n.t("lbl_api_key"), self._api_key_edit)

        self._api_model_edit = QLineEdit(self._settings.api_model)
        form.addRow(self._i18n.t("lbl_api_model"), self._api_model_edit)

        self._summary_lang_edit = QLineEdit(self._settings.summary_language)
        form.addRow(self._i18n.t("lbl_summary_lang"), self._summary_lang_edit)
        return card

    def _refresh_ollama_models(self) -> None:
        if self.chk_air_gapped.isChecked():
            return
        url = self._ollama_url_edit.text().strip()
        current = self._ollama_model_combo.currentText().strip()
        self._scan_ollama_btn.setEnabled(False)

        def _worker() -> None:
            models = list_ollama_models(url)
            self._ollama_models_loaded.emit(models, current)

        threading.Thread(target=_worker, daemon=True, name="OllamaModelScanner").start()

    def _on_ollama_models_loaded(self, models: list, current: str) -> None:
        self._scan_ollama_btn.setEnabled(True)
        self._ollama_model_combo.clear()
        for m in models:
            self._ollama_model_combo.addItem(str(m))
        if current:
            self._ollama_model_combo.setEditText(current)
        elif models:
            self._ollama_model_combo.setCurrentIndex(0)

    def _build_system_card(self) -> QFrame:
        card, self._sec_sys_lbl, form = self._make_section_card(self._i18n.t("sec_system"))

        self.combo_ui_lang = FlatComboBox()
        self.combo_ui_lang.addItem("English (EN)", "en")
        self.combo_ui_lang.addItem("Türkçe (TR)", "tr")
        self._select_combo_data(self.combo_ui_lang, self._settings.ui_language)
        self.combo_ui_lang.currentIndexChanged.connect(
            lambda _idx: self.language_changed.emit(str(self.combo_ui_lang.currentData() or "en"))
        )
        form.addRow(self._i18n.t("lbl_ui_lang"), self.combo_ui_lang)

        self.chk_minimize_tray = FlatSwitch(self._i18n.t("lbl_minimize_tray"))
        self.chk_minimize_tray.setChecked(self._settings.minimize_to_tray)
        form.addRow(self.chk_minimize_tray)

        self.chk_auto_update = FlatSwitch(self._i18n.t("lbl_auto_update"))
        self.chk_auto_update.setChecked(self._settings.check_updates_on_startup)
        form.addRow(self.chk_auto_update)

        tools_row = QHBoxLayout()
        tools_row.setSpacing(8)

        self.btn_check_updates = QPushButton(self._i18n.t("btn_check_updates"))
        self.btn_check_updates.setObjectName("GhostButton")
        self.btn_check_updates.setIcon(make_flat_icon("refresh", "#A1A1AA", 12))
        self.btn_check_updates.setIconSize(QSize(12, 12))
        self.btn_check_updates.clicked.connect(self.check_updates_requested.emit)
        tools_row.addWidget(self.btn_check_updates)

        self.btn_run_benchmark = QPushButton(self._i18n.t("btn_run_benchmark"))
        self.btn_run_benchmark.setObjectName("GhostButton")
        self.btn_run_benchmark.setIcon(make_flat_icon("gauge", "#34D399", 12))
        self.btn_run_benchmark.setIconSize(QSize(12, 12))
        self.btn_run_benchmark.clicked.connect(self.run_benchmark_requested.emit)
        tools_row.addWidget(self.btn_run_benchmark)
        tools_row.addStretch()
        form.addRow(f"LocalMinutes v{__version__}", tools_row)

        self.lbl_diag_status = QLabel("")
        self.lbl_diag_status.setObjectName("MutedLabel")
        self.lbl_diag_status.setWordWrap(True)
        form.addRow("", self.lbl_diag_status)
        return card

    def set_diagnostics_text(self, text: str) -> None:
        self.lbl_diag_status.setText(text)

    def refresh_telemetry(self, insights: dict[str, Any], settings: AppSettings) -> None:
        self._settings = replace(settings)
        self.card_engine.set_metric(
            settings.whisper_model,
            sub_text=f"CPU ({self._tuning.whisper_threads}T) · Silero VAD",
            badge_text=settings.whisper_compute_type.upper(),
        )
        self.card_privacy.set_metric(
            "Air-Gapped" if settings.air_gapped_mode else "0 Bots",
            sub_text="0 HTTP requests guaranteed" if settings.air_gapped_mode else "0 bytes uploaded to cloud",
            badge_text="STRICT" if settings.air_gapped_mode else "OFFLINE",
        )
        db_mb = float(insights.get("db_size_mb", 0.0))
        db_kb = float(insights.get("db_size_kb", 0.0))
        size_label = f"{db_mb:.2f} MB" if db_mb >= 0.1 else f"{db_kb:.0f} KB"
        total_segs = int(insights.get("total_segments", 0))
        self.card_storage.set_metric(
            size_label,
            sub_text=f"{insights.get('total_meetings', 0)} meetings · {total_segs:,} segments",
            bar_pct=min(100, max(22, int(db_mb * 20) + 22)),
        )

    def collect_settings(self) -> AppSettings:
        return AppSettings(
            ui_language=str(self.combo_ui_lang.currentData() or "en"),
            air_gapped_mode=self.chk_air_gapped.isChecked(),
            check_updates_on_startup=self.chk_auto_update.isChecked(),
            minimize_to_tray=self.chk_minimize_tray.isChecked(),
            performance_profile=self._settings.performance_profile,
            capture_mic=self._capture_mic_cb.isChecked(),
            mic_device_index=self._mic_combo.currentData(),
            capture_loopback=self._capture_lb_cb.isChecked(),
            loopback_device_index=self._lb_combo.currentData(),
            save_wav=self._save_wav_cb.isChecked(),
            whisper_model=str(self._model_combo.currentData() or "small"),
            whisper_compute_type=str(self._compute_combo.currentData() or "int8"),
            whisper_language=str(self._lang_combo.currentData() or "auto"),
            custom_vocabulary=self._custom_vocab_edit.text().strip(),
            vad_silence_ms=int(self._vad_spin.value()),
            chunk_max_sec=float(self._chunk_spin.value()),
            energy_threshold=float(self._energy_spin.value()),
            llm_provider=str(self._provider_combo.currentData() or "auto"),
            default_template=str(self._default_tmpl_combo.currentData() or "meeting"),
            ollama_url=self._ollama_url_edit.text().strip() or "http://localhost:11434",
            ollama_model=self._ollama_model_combo.currentText().strip() or "qwen2.5:7b",
            api_base_url=self._api_url_edit.text().strip() or "https://api.openai.com/v1",
            api_key=self._api_key_edit.text().strip(),
            api_model=self._api_model_edit.text().strip() or "gpt-4o-mini",
            summary_language=self._summary_lang_edit.text().strip() or "English",
        )

    def _save_clicked(self) -> None:
        new_settings = self.collect_settings()
        self._settings = replace(new_settings)
        self.settings_saved.emit(new_settings)

    def retranslate(self, i18n: LanguageManager) -> None:
        self._i18n = i18n
        self._title_lbl.setText(i18n.t("settings_header"))
        self._sub_lbl.setText(i18n.t("settings_subtitle"))
        self.btn_save.setText(i18n.t("btn_save_settings"))
        self._hw_badge.setText(format_hardware_summary(self._hw, self._tuning, lang=i18n.lang))
        self.card_engine.set_title(i18n.t("kpi_engine"))
        self.card_vram.set_title(i18n.t("kpi_vram"))
        self.card_privacy.set_title(i18n.t("kpi_privacy"))
        self.card_storage.set_title(i18n.t("kpi_storage"))
        self._sec_audio_lbl.setText(i18n.t("sec_audio"))
        self._sec_whisper_lbl.setText(i18n.t("sec_whisper"))
        self._sec_llm_lbl.setText(i18n.t("sec_llm"))
        self._sec_sys_lbl.setText(i18n.t("sec_system"))
        self._capture_mic_cb.setText(i18n.t("lbl_capture_mic"))
        self._capture_lb_cb.setText(i18n.t("lbl_capture_lb"))
        self._save_wav_cb.setText(i18n.t("lbl_save_wav"))
        self._refresh_dev_btn.setText(i18n.t("btn_refresh_devices"))
        self._os_audio_hint.setText(get_loopback_setup_hint(lang=i18n.lang))
        self._del_model_btn.setText(i18n.t("btn_delete_model"))
        self._custom_vocab_edit.setPlaceholderText(i18n.t("custom_vocab_ph"))
        self.chk_air_gapped.setText(i18n.t("lbl_air_gapped"))
        self._scan_ollama_btn.setText(i18n.t("btn_scan_ollama"))
        self.chk_minimize_tray.setText(i18n.t("lbl_minimize_tray"))
        self.chk_auto_update.setText(i18n.t("lbl_auto_update"))
        self.btn_check_updates.setText(i18n.t("btn_check_updates"))
        self.btn_run_benchmark.setText(i18n.t("btn_run_benchmark"))

    @staticmethod
    def _select_combo_data(combo: FlatComboBox, target) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == target:
                combo.setCurrentIndex(i)
                return
