"""Tabbed Settings dialog with Audio Devices, Whisper Model Manager, and LLM Summarizer."""

from __future__ import annotations

import threading
from dataclasses import replace

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from localminutes.audio.devices import list_audio_devices
from localminutes.models import SUMMARY_TEMPLATES, AppSettings
from localminutes.summarization.summarizer import list_ollama_models
from localminutes.transcription.engine import WHISPER_MODELS, WhisperEngine, list_cached_models


class SettingsDialog(QDialog):
    """Configure audio channels, faster-whisper model cache, and LLM provider."""

    _model_dl_done = pyqtSignal(bool, str)

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LocalMinutes — Ayarlar")
        self.setMinimumWidth(560)
        self._settings = replace(settings)
        self._model_dl_done.connect(self._on_model_download_finished)

        root = QVBoxLayout(self)
        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        self._build_audio_tab()
        self._build_whisper_tab()
        self._build_llm_tab()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Kaydet")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_audio_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setSpacing(10)

        mics, loopbacks = list_audio_devices()

        self._capture_mic_cb = QCheckBox("Mikrofon kanalını kaydet ('Sen')")
        self._capture_mic_cb.setChecked(self._settings.capture_mic)
        form.addRow(self._capture_mic_cb)

        self._mic_combo = QComboBox()
        self._mic_combo.addItem("Varsayılan Mikrofon (Otomatik)", None)
        for dev in mics:
            self._mic_combo.addItem(dev.display_name, dev.index)
        self._select_combo_data(self._mic_combo, self._settings.mic_device_index)
        form.addRow("Mikrofon Cihazı:", self._mic_combo)

        self._capture_lb_cb = QCheckBox("Sistem sesini kaydet — WASAPI Loopback ('Karşı Taraf')")
        self._capture_lb_cb.setChecked(self._settings.capture_loopback)
        form.addRow(self._capture_lb_cb)

        self._lb_combo = QComboBox()
        self._lb_combo.addItem("Varsayılan Hoparlör Loopback (Otomatik)", None)
        for dev in loopbacks:
            self._lb_combo.addItem(dev.display_name, dev.index)
        self._select_combo_data(self._lb_combo, self._settings.loopback_device_index)
        form.addRow("Sistem Sesi (Loopback):", self._lb_combo)

        self._save_wav_cb = QCheckBox("Ham ses kayıtlarını ayrı WAV dosyaları olarak sakla")
        self._save_wav_cb.setChecked(self._settings.save_wav)
        form.addRow(self._save_wav_cb)

        self._tabs.addTab(tab, "Ses Cihazları")

    def _build_whisper_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setSpacing(10)

        model_row = QHBoxLayout()
        self._model_combo = QComboBox()
        self._populate_whisper_models()
        self._select_combo_data(self._model_combo, self._settings.whisper_model)
        self._model_combo.currentIndexChanged.connect(self._update_model_cache_label)
        model_row.addWidget(self._model_combo, 1)

        self._dl_model_btn = QPushButton("Modeli İndir")
        self._dl_model_btn.setToolTip("Seçili Whisper modelini şimdiden offline önbelleğe indir")
        self._dl_model_btn.clicked.connect(self._download_selected_model)
        model_row.addWidget(self._dl_model_btn)
        form.addRow("Whisper Modeli:", model_row)

        self._model_status_label = QLabel("")
        self._model_status_label.setObjectName("MutedLabel")
        self._update_model_cache_label()
        form.addRow("", self._model_status_label)

        self._compute_combo = QComboBox()
        for c in ["int8", "int8_float32", "float32"]:
            self._compute_combo.addItem(c, c)
        self._select_combo_data(self._compute_combo, self._settings.whisper_compute_type)
        form.addRow("Hesaplama Tipi (CPU):", self._compute_combo)

        self._lang_combo = QComboBox()
        langs = [("Türkçe (tr)", "tr"), ("İngilizce (en)", "en"), ("Otomatik Algıla", "auto")]
        for label, code in langs:
            self._lang_combo.addItem(label, code)
        self._select_combo_data(self._lang_combo, self._settings.whisper_language)
        form.addRow("Konuşma Dili:", self._lang_combo)

        self._vad_spin = QSpinBox()
        self._vad_spin.setRange(300, 3000)
        self._vad_spin.setSingleStep(100)
        self._vad_spin.setSuffix(" ms")
        self._vad_spin.setValue(self._settings.vad_silence_ms)
        form.addRow("Sessizlik Bitiş Süresi (VAD):", self._vad_spin)

        self._chunk_spin = QDoubleSpinBox()
        self._chunk_spin.setRange(4.0, 30.0)
        self._chunk_spin.setSingleStep(1.0)
        self._chunk_spin.setSuffix(" sn")
        self._chunk_spin.setValue(self._settings.chunk_max_sec)
        form.addRow("Maksimum Parça Süresi:", self._chunk_spin)

        self._energy_spin = QDoubleSpinBox()
        self._energy_spin.setDecimals(4)
        self._energy_spin.setRange(0.001, 0.1)
        self._energy_spin.setSingleStep(0.001)
        self._energy_spin.setValue(self._settings.energy_threshold)
        form.addRow("Ses Algılama Eşiği (RMS):", self._energy_spin)

        self._tabs.addTab(tab, "Deşifre (Whisper)")

    def _populate_whisper_models(self) -> None:
        cached = list_cached_models()
        self._model_combo.clear()
        for m in WHISPER_MODELS:
            suffix = "  ✓ (Hazır)" if m in cached else ""
            self._model_combo.addItem(f"{m}{suffix}", m)

    def _update_model_cache_label(self) -> None:
        selected = str(self._model_combo.currentData() or "small")
        cached = list_cached_models()
        if selected in cached:
            self._model_status_label.setText(f"✓ '{selected}' modeli bilgisayarınızda indirilmiş (tamamen offline hazır).")
            self._dl_model_btn.setText("Hazır ✓")
        else:
            self._model_status_label.setText(
                f"↓ '{selected}' henüz indirilmemiş. İlk kayıtta veya 'Modeli İndir' ile indirilir."
            )
            self._dl_model_btn.setText("Modeli İndir")

    def _download_selected_model(self) -> None:
        model_name = str(self._model_combo.currentData() or "small")
        compute = str(self._compute_combo.currentData() or "int8")
        self._dl_model_btn.setEnabled(False)
        self._dl_model_btn.setText("İndiriliyor...")
        self._model_status_label.setText(f"'{model_name}' modeli indiriliyor, lütfen bekleyin...")

        def _worker() -> None:
            try:
                eng = WhisperEngine(model_size=model_name, compute_type=compute)
                eng.load()
                self._model_dl_done.emit(True, f"✓ '{model_name}' başarıyla indirildi ve hazır.")
            except Exception as exc:
                self._model_dl_done.emit(False, f"İndirme hatası: {exc}")

        threading.Thread(target=_worker, daemon=True, name="ModelDownloader").start()

    def _on_model_download_finished(self, ok: bool, message: str) -> None:
        selected = str(self._model_combo.currentData() or "small")
        self._populate_whisper_models()
        self._select_combo_data(self._model_combo, selected)
        self._dl_model_btn.setEnabled(True)
        self._update_model_cache_label()
        self._model_status_label.setText(message)

    def _build_llm_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setSpacing(10)

        self._provider_combo = QComboBox()
        self._provider_combo.addItem("Otomatik (Ollama → Yerleşik Offline)", "auto")
        self._provider_combo.addItem("Lokal Ollama (%100 Offline LLM)", "ollama")
        self._provider_combo.addItem("Yerleşik Offline Motor (Sıfır Kurulum)", "local_extractive")
        self._provider_combo.addItem("OpenAI Uyumlu API (Opsiyonel)", "openai_compatible")
        self._select_combo_data(self._provider_combo, self._settings.llm_provider)
        form.addRow("Özet Sağlayıcısı:", self._provider_combo)

        self._default_tmpl_combo = QComboBox()
        for key, info in SUMMARY_TEMPLATES.items():
            self._default_tmpl_combo.addItem(info["label"], key)
        self._select_combo_data(self._default_tmpl_combo, self._settings.default_template)
        form.addRow("Varsayılan Şablon:", self._default_tmpl_combo)

        self._ollama_url_edit = QLineEdit(self._settings.ollama_url)
        form.addRow("Ollama URL:", self._ollama_url_edit)

        ollama_row = QHBoxLayout()
        self._ollama_model_combo = QComboBox()
        self._ollama_model_combo.setEditable(True)
        self._ollama_model_combo.setEditText(self._settings.ollama_model)
        refresh_btn = QPushButton("Modelleri Tara")
        refresh_btn.clicked.connect(self._refresh_ollama_models)
        ollama_row.addWidget(self._ollama_model_combo, 1)
        ollama_row.addWidget(refresh_btn)
        form.addRow("Ollama Modeli:", ollama_row)

        self._api_url_edit = QLineEdit(self._settings.api_base_url)
        form.addRow("API Base URL:", self._api_url_edit)

        self._api_key_edit = QLineEdit(self._settings.api_key)
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("sk-...")
        form.addRow("API Anahtarı:", self._api_key_edit)

        self._api_model_edit = QLineEdit(self._settings.api_model)
        form.addRow("API Modeli:", self._api_model_edit)

        self._summary_lang_edit = QLineEdit(self._settings.summary_language)
        form.addRow("Özet Dili:", self._summary_lang_edit)

        note = QLabel(
            "İpucu: 'Otomatik' modda önce lokal Ollama denenir; Ollama çalışmıyorsa sıfır kurulumlu "
            "yerleşik offline özet motoru anında devreye girer."
        )
        note.setObjectName("MutedLabel")
        note.setWordWrap(True)
        form.addRow(note)

        self._tabs.addTab(tab, "Özetleme (LLM)")

    def _refresh_ollama_models(self) -> None:
        current = self._ollama_model_combo.currentText().strip()
        models = list_ollama_models(self._ollama_url_edit.text().strip())
        self._ollama_model_combo.clear()
        for m in models:
            self._ollama_model_combo.addItem(m)
        if current:
            self._ollama_model_combo.setEditText(current)
        elif models:
            self._ollama_model_combo.setCurrentIndex(0)

    @staticmethod
    def _select_combo_data(combo: QComboBox, target) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == target:
                combo.setCurrentIndex(i)
                return

    def _on_accept(self) -> None:
        self._settings.capture_mic = self._capture_mic_cb.isChecked()
        self._settings.mic_device_index = self._mic_combo.currentData()
        self._settings.capture_loopback = self._capture_lb_cb.isChecked()
        self._settings.loopback_device_index = self._lb_combo.currentData()
        self._settings.save_wav = self._save_wav_cb.isChecked()

        self._settings.whisper_model = str(self._model_combo.currentData())
        self._settings.whisper_compute_type = str(self._compute_combo.currentData())
        self._settings.whisper_language = str(self._lang_combo.currentData())
        self._settings.vad_silence_ms = int(self._vad_spin.value())
        self._settings.chunk_max_sec = float(self._chunk_spin.value())
        self._settings.energy_threshold = float(self._energy_spin.value())

        self._settings.llm_provider = str(self._provider_combo.currentData())
        self._settings.default_template = str(self._default_tmpl_combo.currentData())
        self._settings.ollama_url = self._ollama_url_edit.text().strip() or "http://localhost:11434"
        self._settings.ollama_model = self._ollama_model_combo.currentText().strip() or "qwen2.5:7b"
        self._settings.api_base_url = self._api_url_edit.text().strip() or "https://api.openai.com/v1"
        self._settings.api_key = self._api_key_edit.text().strip()
        self._settings.api_model = self._api_model_edit.text().strip() or "gpt-4o-mini"
        self._settings.summary_language = self._summary_lang_edit.text().strip() or "Türkçe"
        self.accept()

    def get_settings(self) -> AppSettings:
        return self._settings
