"""Live & archived speaker-labeled transcript viewer with in-text search highlight."""

from __future__ import annotations

import html
import re

from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from localminutes.export.exporter import format_timestamp
from localminutes.models import TranscriptSegment


class TranscriptView(QWidget):
    """Displays speaker-labeled transcript segments with search highlighting."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: list[TranscriptSegment] = []
        self._filter_query: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Canlı Transkript")
        title.setObjectName("SectionTitle")
        header.addWidget(title)

        self._count_label = QLabel("0 satır")
        self._count_label.setObjectName("MutedLabel")
        header.addWidget(self._count_label)
        header.addStretch()

        self._auto_scroll_cb = QCheckBox("Otomatik kaydır")
        self._auto_scroll_cb.setChecked(True)
        header.addWidget(self._auto_scroll_cb)
        layout.addLayout(header)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Transkript içinde hızlı ara...")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._search_box)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setPlaceholderText(
            "Kaydı başlattığınızda konuşmalar burada canlı olarak ('Sen' / 'Karşı Taraf') görünecektir."
        )
        layout.addWidget(self._browser, 1)

    def set_segments(self, segments: list[TranscriptSegment]) -> None:
        self._segments = list(segments)
        self._render()

    def append_segment(self, segment: TranscriptSegment) -> None:
        self._segments.append(segment)
        self._render()
        if self._auto_scroll_cb.isChecked():
            sb = self._browser.verticalScrollBar()
            if sb is not None:
                sb.setValue(sb.maximum())

    def clear(self) -> None:
        self._segments.clear()
        self._browser.clear()
        self._count_label.setText("0 satır")

    def _on_filter_changed(self, text: str) -> None:
        self._filter_query = text.strip()
        self._render()

    def _render(self) -> None:
        query = self._filter_query
        if not self._segments:
            self._browser.clear()
            self._count_label.setText("0 satır")
            return

        blocks: list[str] = []
        matched_count = 0
        pattern = re.compile(re.escape(query), re.IGNORECASE) if query else None

        for seg in self._segments:
            if pattern and not (pattern.search(seg.text) or pattern.search(seg.speaker)):
                continue
            matched_count += 1
            is_user = seg.speaker == "Sen"
            badge_bg = "#12382c" if is_user else "#172a4a"
            badge_fg = "#34d399" if is_user else "#60a5fa"
            border_color = "#10b981" if is_user else "#3b82f6"
            ts = format_timestamp(seg.start_sec)

            escaped_text = html.escape(seg.text.strip())
            if pattern:
                escaped_text = pattern.sub(
                    lambda m: (
                        f'<span style="background-color:#854d0e; color:#fef08a; '
                        f'padding:0 2px; border-radius:2px;">{m.group(0)}</span>'
                    ),
                    escaped_text,
                )

            blocks.append(
                f"""
                <div style="margin-bottom:10px; padding:8px 10px;
                            background-color:#161b26;
                            border-left:3px solid {border_color};
                            border-radius:6px;">
                  <div style="margin-bottom:4px;">
                    <span style="background-color:{badge_bg}; color:{badge_fg};
                                 font-weight:700; font-size:11px;
                                 padding:2px 7px; border-radius:4px;">
                      {html.escape(seg.speaker)}
                    </span>
                    <span style="color:#7d8590; font-size:11px; margin-left:8px;">
                      {ts}
                    </span>
                  </div>
                  <div style="color:#e6edf3; font-size:13px; line-height:1.45;">
                    {escaped_text}
                  </div>
                </div>
                """
            )

        if query:
            self._count_label.setText(f"{matched_count} / {len(self._segments)} eşleşme")
        else:
            self._count_label.setText(f"{len(self._segments)} satır")

        self._browser.setHtml("".join(blocks))
