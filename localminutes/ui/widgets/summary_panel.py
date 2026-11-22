"""AI summary panel showing Overview, Key Points, Decisions, and Action Items."""

from __future__ import annotations

import html
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from localminutes.models import SummaryResult


class SummaryPanel(QWidget):
    """Right-hand panel for displaying and generating structured meeting summaries."""

    summarize_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(290)
        self._summary: Optional[SummaryResult] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Özet & Aksiyonlar")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch()

        self._copy_btn = QPushButton("Kopyala")
        self._copy_btn.setObjectName("ExportButton")
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._copy_summary)
        header.addWidget(self._copy_btn)

        self._gen_btn = QPushButton("✦ Özet Oluştur")
        self._gen_btn.setObjectName("PrimaryButton")
        self._gen_btn.clicked.connect(self.summarize_requested.emit)
        header.addWidget(self._gen_btn)
        layout.addLayout(header)

        self._meta_label = QLabel("Lokal LLM (Ollama) veya API ile otomatik özet")
        self._meta_label.setObjectName("MutedLabel")
        layout.addWidget(self._meta_label)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setPlaceholderText(
            "Toplantı veya ders bitiminde 'Özet Oluştur' butonuna tıklayarak:\n"
            "• Genel Özet\n"
            "• Öne Çıkan Noktalar\n"
            "• Alınan Kararlar\n"
            "• Yapılacaklar Listesi (Action Items)\n"
            "çıkarabilirsiniz."
        )
        layout.addWidget(self._browser, 1)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self._gen_btn.setEnabled(not busy)
        if busy:
            self._gen_btn.setText("Özetleniyor...")
            if message:
                self._meta_label.setText(message)
        else:
            self._gen_btn.setText("✦ Özet Oluştur")

    def set_summary(self, summary: Optional[SummaryResult]) -> None:
        self._summary = summary
        if summary is None:
            self._browser.clear()
            self._copy_btn.setEnabled(False)
            self._meta_label.setText("Henüz özet oluşturulmadı.")
            return

        self._copy_btn.setEnabled(True)
        model_info = summary.model_used or "LLM"
        time_info = summary.generated_at.replace("T", " ")[:16] if summary.generated_at else ""
        self._meta_label.setText(f"Model: {model_info}  •  {time_info}")

        sections: list[str] = []
        if summary.overview:
            sections.append(
                f"""
                <div style="margin-bottom:14px;">
                  <div style="color:#93c5fd; font-weight:700; font-size:13px; margin-bottom:5px;">
                    GENEL ÖZET
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
                    ÖNE ÇIKAN NOKTALAR
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
                    ALINAN KARARLAR
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
                    YAPILACAKLAR (ACTION ITEMS)
                  </div>
                  <ul style="list-style-type:none; margin:0; padding-left:4px; color:#e6edf3;">{items}</ul>
                </div>
                """
            )

        self._browser.setHtml("".join(sections))

    def _copy_summary(self) -> None:
        if not self._summary:
            return
        lines: list[str] = []
        if self._summary.overview:
            lines.append("## Özet\n" + self._summary.overview)
        if self._summary.key_points:
            lines.append("## Öne Çıkan Noktalar\n" + "\n".join(f"- {p}" for p in self._summary.key_points))
        if self._summary.decisions:
            lines.append("## Alınan Kararlar\n" + "\n".join(f"- {d}" for d in self._summary.decisions))
        if self._summary.action_items:
            lines.append("## Yapılacaklar\n" + "\n".join(f"- [ ] {a}" for a in self._summary.action_items))
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("\n\n".join(lines))
            self._copy_btn.setText("Kopyalandı ✓")
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(1500, lambda: self._copy_btn.setText("Kopyala"))
