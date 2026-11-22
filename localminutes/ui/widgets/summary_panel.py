"""AI summary panel with templates and an integrated live Meeting Notes tab."""

from __future__ import annotations

import html
from typing import Optional

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from localminutes.models import SUMMARY_TEMPLATES, SummaryResult


class SummaryPanel(QWidget):
    """Right-hand panel with structured Summary + live Meeting Notes tabs."""

    summarize_requested = pyqtSignal(str)  # template_key
    template_changed = pyqtSignal(str)
    notes_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(310)
        self._summary: Optional[SummaryResult] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, 1)

        # --- Tab 1: AI Summary ---
        summary_tab = QWidget()
        s_layout = QVBoxLayout(summary_tab)
        s_layout.setContentsMargins(8, 8, 8, 8)
        s_layout.setSpacing(8)

        header = QHBoxLayout()
        self._template_combo = QComboBox()
        for key, info in SUMMARY_TEMPLATES.items():
            self._template_combo.addItem(info["label"], key)
        self._template_combo.currentIndexChanged.connect(self._on_template_changed)
        header.addWidget(self._template_combo, 1)

        self._copy_btn = QPushButton("Kopyala")
        self._copy_btn.setObjectName("ExportButton")
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._copy_summary)
        header.addWidget(self._copy_btn)

        self._gen_btn = QPushButton("✦ Özetle")
        self._gen_btn.setObjectName("PrimaryButton")
        self._gen_btn.setToolTip("Seçili şablonla özet oluştur (Ctrl+G)")
        self._gen_btn.clicked.connect(self._emit_summarize)
        header.addWidget(self._gen_btn)
        s_layout.addLayout(header)

        self._meta_label = QLabel("Ollama veya yerleşik offline motor ile anında özet")
        self._meta_label.setObjectName("MutedLabel")
        s_layout.addWidget(self._meta_label)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setPlaceholderText(
            "Toplantı veya ders bitiminde '✦ Özetle' butonuna tıklayarak:\n"
            "• Genel Özet\n"
            "• Öne Çıkan Noktalar / Kavramlar\n"
            "• Alınan Kararlar / Vurgular\n"
            "• Yapılacaklar (Action Items) / Çalışma Soruları\n"
            "çıkarabilirsiniz. Ollama çalışmıyorsa yerleşik %100 offline motor otomatik devreye girer."
        )
        s_layout.addWidget(self._browser, 1)
        self._tabs.addTab(summary_tab, "✦ Özet & Aksiyonlar")

        # --- Tab 2: Live Meeting Notes ---
        notes_tab = QWidget()
        n_layout = QVBoxLayout(notes_tab)
        n_layout.setContentsMargins(8, 8, 8, 8)
        n_layout.setSpacing(6)

        notes_hint = QLabel(
            "Kayıt sırasında aldığınız notlar otomatik kaydedilir ve özetleme + dışa aktarmaya dahil edilir."
        )
        notes_hint.setObjectName("MutedLabel")
        notes_hint.setWordWrap(True)
        n_layout.addWidget(notes_hint)

        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setPlaceholderText("- Önemli tarihler, linkler, aklınıza gelen notlar...")
        n_layout.addWidget(self._notes_edit, 1)

        self._notes_debounce = QTimer(self)
        self._notes_debounce.setSingleShot(True)
        self._notes_debounce.setInterval(500)
        self._notes_debounce.timeout.connect(
            lambda: self.notes_changed.emit(self._notes_edit.toPlainText())
        )
        self._notes_edit.textChanged.connect(self._notes_debounce.start)

        self._tabs.addTab(notes_tab, "📝 Notlar")

    def current_template(self) -> str:
        return str(self._template_combo.currentData() or "meeting")

    def set_template(self, template_key: str) -> None:
        self._template_combo.blockSignals(True)
        for i in range(self._template_combo.count()):
            if self._template_combo.itemData(i) == template_key:
                self._template_combo.setCurrentIndex(i)
                break
        self._template_combo.blockSignals(False)

    def set_notes(self, text: str) -> None:
        self._notes_edit.blockSignals(True)
        self._notes_edit.setPlainText(text)
        self._notes_edit.blockSignals(False)

    def _on_template_changed(self) -> None:
        self.template_changed.emit(self.current_template())

    def _emit_summarize(self) -> None:
        self.summarize_requested.emit(self.current_template())

    def set_busy(self, busy: bool, message: str = "") -> None:
        self._gen_btn.setEnabled(not busy)
        self._template_combo.setEnabled(not busy)
        if busy:
            self._gen_btn.setText("Özetleniyor...")
            if message:
                self._meta_label.setText(message)
        else:
            self._gen_btn.setText("✦ Özetle")

    def set_summary(self, summary: Optional[SummaryResult]) -> None:
        self._summary = summary
        if summary is None:
            self._browser.clear()
            self._copy_btn.setEnabled(False)
            self._meta_label.setText("Henüz özet oluşturulmadı.")
            return

        self._copy_btn.setEnabled(True)
        tmpl = SUMMARY_TEMPLATES.get(summary.template, SUMMARY_TEMPLATES["meeting"])
        model_info = summary.model_used or "LLM"
        time_info = summary.generated_at.replace("T", " ")[:16] if summary.generated_at else ""
        self._meta_label.setText(f"{tmpl['label']}  •  {model_info}  •  {time_info}")

        sections: list[str] = []
        if summary.overview:
            sections.append(
                f"""
                <div style="margin-bottom:14px;">
                  <div style="color:#93c5fd; font-weight:700; font-size:13px; margin-bottom:5px;">
                    {html.escape(tmpl['overview_title'].upper())}
                  </div>
                  <div style="color:#e6edf3; line-height:1.5;">
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
                <div style="margin-bottom:14px;">
                  <div style="color:#a5b4fc; font-weight:700; font-size:13px; margin-bottom:5px;">
                    {html.escape(tmpl['key_points_title'].upper())}
                  </div>
                  <ul style="margin:0; padding-left:18px; color:#e6edf3;">{items}</ul>
                </div>
                """
            )

        if summary.decisions:
            items = "".join(
                f"<li style='margin-bottom:4px;'>{html.escape(d)}</li>" for d in summary.decisions
            )
            sections.append(
                f"""
                <div style="margin-bottom:14px;">
                  <div style="color:#34d399; font-weight:700; font-size:13px; margin-bottom:5px;">
                    {html.escape(tmpl['decisions_title'].upper())}
                  </div>
                  <ul style="margin:0; padding-left:18px; color:#e6edf3;">{items}</ul>
                </div>
                """
            )

        if summary.action_items:
            items = "".join(
                f"<li style='margin-bottom:4px;'>☐ {html.escape(a)}</li>"
                for a in summary.action_items
            )
            sections.append(
                f"""
                <div style="margin-bottom:14px;">
                  <div style="color:#fbbf24; font-weight:700; font-size:13px; margin-bottom:5px;">
                    {html.escape(tmpl['action_items_title'].upper())}
                  </div>
                  <ul style="list-style-type:none; margin:0; padding-left:4px; color:#e6edf3;">{items}</ul>
                </div>
                """
            )

        self._browser.setHtml("".join(sections))

    def _copy_summary(self) -> None:
        if not self._summary:
            return
        tmpl = SUMMARY_TEMPLATES.get(self._summary.template, SUMMARY_TEMPLATES["meeting"])
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
        if self._summary.action_items:
            lines.append(
                f"## {tmpl['action_items_title']}\n"
                + "\n".join(f"- [ ] {a}" for a in self._summary.action_items)
            )
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("\n\n".join(lines))
            self._copy_btn.setText("Kopyalandı ✓")
            QTimer.singleShot(1500, lambda: self._copy_btn.setText("Kopyala"))
