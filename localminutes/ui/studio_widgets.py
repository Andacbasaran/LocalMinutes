"""Studio 2.0 HiDPI vector widgets for LocalMinutes (zero raw emojis, crisp 2x QPainter graphics)."""

from __future__ import annotations

import os
import sys
from collections import deque
from typing import Optional

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from localminutes.hardware import get_app_base_dir


def make_flat_icon(kind: str, color_hex: str = "#FAFAFA", size: int = 14) -> QIcon:
    """Render crisp 2x HiDPI flat vector icons across Windows, macOS, and Linux."""
    px = max(16, int(size) * 2)
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(color_hex)
        stroke = QPen(
            col,
            max(1.8, px * 0.08),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )

        if kind == "record" or kind == "dot":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            r = px * 0.30
            p.drawEllipse(QPointF(px / 2.0, px / 2.0), r, r)

        elif kind == "stop":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(
                int(px * 0.24), int(px * 0.24), int(px * 0.52), int(px * 0.52), 4, 4
            )

        elif kind == "pause":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            w = int(px * 0.17)
            h = int(px * 0.56)
            y = int(px * 0.22)
            p.drawRoundedRect(int(px * 0.26), y, w, h, 2, 2)
            p.drawRoundedRect(int(px * 0.57), y, w, h, 2, 2)

        elif kind == "play":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            poly = QPolygonF(
                [
                    QPointF(px * 0.28, px * 0.20),
                    QPointF(px * 0.80, px * 0.50),
                    QPointF(px * 0.28, px * 0.80),
                ]
            )
            p.drawPolygon(poly)

        elif kind == "mic":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(px * 0.36, px * 0.14, px * 0.28, px * 0.42), px * 0.14, px * 0.14)
            p.drawArc(QRectF(px * 0.24, px * 0.26, px * 0.52, px * 0.44), 195 * 16, 150 * 16)
            p.drawLine(QPointF(px * 0.50, px * 0.70), QPointF(px * 0.50, px * 0.86))
            p.drawLine(QPointF(px * 0.36, px * 0.86), QPointF(px * 0.64, px * 0.86))

        elif kind == "import" or kind == "upload":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(px * 0.50, px * 0.20), QPointF(px * 0.50, px * 0.66))
            p.drawLine(QPointF(px * 0.33, px * 0.37), QPointF(px * 0.50, px * 0.20))
            p.drawLine(QPointF(px * 0.67, px * 0.37), QPointF(px * 0.50, px * 0.20))
            p.drawLine(QPointF(px * 0.20, px * 0.64), QPointF(px * 0.20, px * 0.82))
            p.drawLine(QPointF(px * 0.20, px * 0.82), QPointF(px * 0.80, px * 0.82))
            p.drawLine(QPointF(px * 0.80, px * 0.82), QPointF(px * 0.80, px * 0.64))

        elif kind == "export" or kind == "download":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(px * 0.50, px * 0.18), QPointF(px * 0.50, px * 0.64))
            p.drawLine(QPointF(px * 0.33, px * 0.48), QPointF(px * 0.50, px * 0.64))
            p.drawLine(QPointF(px * 0.67, px * 0.48), QPointF(px * 0.50, px * 0.64))
            p.drawLine(QPointF(px * 0.20, px * 0.66), QPointF(px * 0.20, px * 0.82))
            p.drawLine(QPointF(px * 0.20, px * 0.82), QPointF(px * 0.80, px * 0.82))
            p.drawLine(QPointF(px * 0.80, px * 0.82), QPointF(px * 0.80, px * 0.66))

        elif kind == "star" or kind == "star_filled":
            cx, cy = px / 2.0, px / 2.0
            r_out = px * 0.36
            r_in = px * 0.16
            import math

            pts = []
            for i in range(10):
                angle = -math.pi / 2.0 + i * (math.pi / 5.0)
                r = r_out if i % 2 == 0 else r_in
                pts.append(QPointF(cx + r * math.cos(angle), cy + r * math.sin(angle)))
            poly = QPolygonF(pts)
            if kind == "star_filled":
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
            else:
                p.setPen(stroke)
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(poly)

        elif kind == "edit":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(px * 0.22, px * 0.78), QPointF(px * 0.66, px * 0.22))
            p.drawLine(QPointF(px * 0.66, px * 0.22), QPointF(px * 0.78, px * 0.34))
            p.drawLine(QPointF(px * 0.78, px * 0.34), QPointF(px * 0.34, px * 0.78))
            p.drawLine(QPointF(px * 0.22, px * 0.78), QPointF(px * 0.34, px * 0.78))

        elif kind == "trash":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(px * 0.20, px * 0.28), QPointF(px * 0.80, px * 0.28))
            p.drawLine(QPointF(px * 0.38, px * 0.18), QPointF(px * 0.62, px * 0.18))
            p.drawRoundedRect(QRectF(px * 0.28, px * 0.28, px * 0.44, px * 0.54), 3, 3)
            p.drawLine(QPointF(px * 0.43, px * 0.44), QPointF(px * 0.43, px * 0.68))
            p.drawLine(QPointF(px * 0.57, px * 0.44), QPointF(px * 0.57, px * 0.68))

        elif kind == "sparkles":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            cx, cy = px * 0.46, px * 0.50
            r = px * 0.32
            ir = px * 0.10
            poly = QPolygonF(
                [
                    QPointF(cx, cy - r),
                    QPointF(cx + ir, cy - ir),
                    QPointF(cx + r, cy),
                    QPointF(cx + ir, cy + ir),
                    QPointF(cx, cy + r),
                    QPointF(cx - ir, cy + ir),
                    QPointF(cx - r, cy),
                    QPointF(cx - ir, cy - ir),
                ]
            )
            p.drawPolygon(poly)
            p.drawEllipse(QPointF(px * 0.78, px * 0.24), px * 0.08, px * 0.08)

        elif kind == "plus":
            p.setPen(stroke)
            p.drawLine(QPointF(px * 0.50, px * 0.22), QPointF(px * 0.50, px * 0.78))
            p.drawLine(QPointF(px * 0.22, px * 0.50), QPointF(px * 0.78, px * 0.50))

        elif kind == "search":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(px * 0.44, px * 0.44), px * 0.24, px * 0.24)
            p.drawLine(QPointF(px * 0.62, px * 0.62), QPointF(px * 0.80, px * 0.80))

        elif kind == "check":
            p.setPen(stroke)
            p.drawLine(QPointF(px * 0.22, px * 0.52), QPointF(px * 0.42, px * 0.72))
            p.drawLine(QPointF(px * 0.42, px * 0.72), QPointF(px * 0.78, px * 0.28))

        elif kind == "copy":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(px * 0.34, px * 0.30, px * 0.46, px * 0.52), 3, 3)
            p.drawLine(QPointF(px * 0.22, px * 0.66), QPointF(px * 0.22, px * 0.20))
            p.drawLine(QPointF(px * 0.22, px * 0.20), QPointF(px * 0.64, px * 0.20))

        elif kind == "shield":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(px * 0.50, px * 0.14)
            path.lineTo(px * 0.80, px * 0.26)
            path.lineTo(px * 0.76, px * 0.58)
            path.quadTo(px * 0.66, px * 0.78, px * 0.50, px * 0.86)
            path.quadTo(px * 0.34, px * 0.78, px * 0.24, px * 0.58)
            path.lineTo(px * 0.20, px * 0.26)
            path.closeSubpath()
            p.drawPath(path)

        elif kind == "notes":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(px * 0.20, px * 0.16, px * 0.60, px * 0.68), 4, 4)
            p.drawLine(QPointF(px * 0.34, px * 0.38), QPointF(px * 0.66, px * 0.38))
            p.drawLine(QPointF(px * 0.34, px * 0.54), QPointF(px * 0.66, px * 0.54))
            p.drawLine(QPointF(px * 0.34, px * 0.70), QPointF(px * 0.54, px * 0.70))

        elif kind == "chat":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(px * 0.16, px * 0.20, px * 0.68, px * 0.48), 5, 5)
            p.drawLine(QPointF(px * 0.32, px * 0.68), QPointF(px * 0.26, px * 0.82))
            p.drawLine(QPointF(px * 0.26, px * 0.82), QPointF(px * 0.46, px * 0.68))

        elif kind == "chart" or kind == "gauge":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            bw = int(px * 0.16)
            p.drawRoundedRect(int(px * 0.16), int(px * 0.54), bw, int(px * 0.30), 2, 2)
            p.drawRoundedRect(int(px * 0.42), int(px * 0.34), bw, int(px * 0.50), 2, 2)
            p.drawRoundedRect(int(px * 0.68), int(px * 0.18), bw, int(px * 0.66), 2, 2)

        elif kind == "clock":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(px * 0.50, px * 0.50), px * 0.33, px * 0.33)
            p.drawLine(QPointF(px * 0.50, px * 0.30), QPointF(px * 0.50, px * 0.50))
            p.drawLine(QPointF(px * 0.50, px * 0.50), QPointF(px * 0.66, px * 0.58))

        elif kind == "refresh":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(px * 0.20, px * 0.20, px * 0.60, px * 0.60)
            p.drawArc(rect, 35 * 16, 285 * 16)
            p.drawLine(QPointF(px * 0.78, px * 0.20), QPointF(px * 0.78, px * 0.38))
            p.drawLine(QPointF(px * 0.78, px * 0.38), QPointF(px * 0.60, px * 0.38))

        elif kind == "settings":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(px * 0.50, px * 0.50), px * 0.18, px * 0.18)
            p.drawEllipse(QPointF(px * 0.50, px * 0.50), px * 0.34, px * 0.34)

        elif kind == "users" or kind == "rename":
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(px * 0.42, px * 0.34), px * 0.14, px * 0.14)
            p.drawArc(QRectF(px * 0.18, px * 0.52, px * 0.48, px * 0.36), 0, 180 * 16)
            p.drawLine(QPointF(px * 0.68, px * 0.36), QPointF(px * 0.84, px * 0.36))
            p.drawLine(QPointF(px * 0.76, px * 0.28), QPointF(px * 0.84, px * 0.36))
            p.drawLine(QPointF(px * 0.76, px * 0.44), QPointF(px * 0.84, px * 0.36))

        elif kind == "close":
            p.setPen(stroke)
            p.drawLine(QPointF(px * 0.26, px * 0.26), QPointF(px * 0.74, px * 0.74))
            p.drawLine(QPointF(px * 0.74, px * 0.26), QPointF(px * 0.26, px * 0.74))

        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            s = int(px * 0.34)
            m = (px - s) // 2
            p.drawRoundedRect(m, m, s, s, 3, 3)
    finally:
        p.end()
    pix.setDevicePixelRatio(2.0)
    return QIcon(pix)


def create_app_pixmap(size: int = 64) -> QPixmap:
    """
    Load LocalMinutes obsidian geometric icon at 2x HiDPI resolution,
    with procedural flat fallback matching assets/app_icon.svg.
    """
    search_roots = [get_app_base_dir()]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass not in search_roots:
        search_roots.append(meipass)
    target_px = max(16, int(size) * 2)
    for root in search_roots:
        for fname in ("app_icon.png", "app_icon.ico"):
            icon_path = os.path.join(root, "assets", fname)
            if os.path.exists(icon_path):
                src_pix = QPixmap(icon_path)
                if not src_pix.isNull():
                    scaled = src_pix.scaled(
                        target_px,
                        target_px,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    rounded = QPixmap(target_px, target_px)
                    rounded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(rounded)
                    try:
                        p.setRenderHint(QPainter.RenderHint.Antialiasing)
                        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                        path = QPainterPath()
                        rad = target_px * 0.22
                        path.addRoundedRect(0.0, 0.0, float(target_px), float(target_px), rad, rad)
                        p.setClipPath(path)
                        p.drawPixmap(0, 0, scaled)
                    finally:
                        p.end()
                    rounded.setDevicePixelRatio(2.0)
                    return rounded

    # Procedural fallback matching assets/app_icon.svg (Obsidian Tile + Dual Wave + Notes Lines)
    pix = QPixmap(target_px, target_px)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = target_px / 512.0

        # Matte obsidian tile
        p.setBrush(QColor("#111114"))
        p.setPen(QPen(QColor("#27272E"), max(1.0, 6.0 * k)))
        p.drawRoundedRect(QRectF(12 * k, 12 * k, 488 * k, 488 * k), 114 * k, 114 * k)

        # Dual-channel acoustic bars (left = Emerald Mint Mic, right = Sky Remote)
        p.setPen(Qt.PenStyle.NoPen)
        emerald = QColor("#10B981")
        sky = QColor("#38BDF8")
        white = QColor("#FAFAFA")
        muted = QColor("#52525B")

        bars = [
            (116, 176, 30, 118, emerald),
            (164, 126, 30, 168, emerald),
            (212, 162, 30, 132, white),
            (260, 140, 30, 154, white),
            (308, 172, 30, 122, sky),
            (356, 198, 30, 96, sky),
        ]
        for bx, by, bw, bh, bcol in bars:
            p.setBrush(bcol)
            p.drawRoundedRect(QRectF(bx * k, by * k, bw * k, bh * k), 15 * k, 15 * k)

        # Structured meeting notes lines underneath
        p.setBrush(white)
        p.drawRoundedRect(QRectF(116 * k, 336 * k, 280 * k, 24 * k), 12 * k, 12 * k)
        p.setBrush(emerald)
        p.drawRoundedRect(QRectF(116 * k, 378 * k, 186 * k, 24 * k), 12 * k, 12 * k)
        p.setBrush(muted)
        p.drawRoundedRect(QRectF(318 * k, 378 * k, 78 * k, 24 * k), 12 * k, 12 * k)
    finally:
        p.end()
    pix.setDevicePixelRatio(2.0)
    return pix


def create_app_icon() -> QIcon:
    search_roots = [get_app_base_dir()]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass not in search_roots:
        search_roots.append(meipass)
    for root in search_roots:
        for fname in ("app_icon.ico", "app_icon.png"):
            ico_path = os.path.join(root, "assets", fname)
            if os.path.exists(ico_path):
                return QIcon(ico_path)
    return QIcon(create_app_pixmap(64))


class SidebarNavButton(QPushButton):
    """Studio 2.0 sidebar navigation item with Emerald Mint active indicator and optional badge."""

    def __init__(self, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._label_text = label
        self._badge_text = ""
        self._badge_kind = "muted"  # 'muted' | 'emerald' | 'live'
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34)
        self.setText("")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(9)

        self._dot = QFrame(self)
        self._dot.setFixedSize(6, 6)
        self._dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._dot)

        self._lbl = QLabel(label, self)
        self._lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._lbl, stretch=1)

        self._badge = QLabel("", self)
        self._badge.setFixedHeight(18)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._badge.hide()
        lay.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)

        self._refresh_style()

    def set_nav_text(self, label: str) -> None:
        self._label_text = label
        self._lbl.setText(label)

    def set_badge(self, text: str, kind: str = "muted") -> None:
        self._badge_text = str(text or "").strip()
        self._badge_kind = kind
        if not self._badge_text:
            self._badge.hide()
            return
        self._badge.setText(self._badge_text)
        if kind == "live":
            self._badge.setStyleSheet(
                "color: #FB7185; background-color: #281219; border: 1px solid #591C2E; "
                "border-radius: 4px; padding: 1px 6px; font-size: 9.5px; font-weight: 700;"
            )
        elif kind == "emerald":
            self._badge.setStyleSheet(
                "color: #34D399; background-color: #0E261E; border: 1px solid #1C4A3A; "
                "border-radius: 4px; padding: 1px 6px; font-size: 9.5px; font-weight: 700;"
            )
        else:
            self._badge.setStyleSheet(
                "color: #A1A1AA; background-color: #1B1B21; border: 1px solid #2A2A32; "
                "border-radius: 4px; padding: 1px 6px; font-size: 9.5px; font-weight: 700;"
            )
        self._badge.show()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._refresh_style()

    def _refresh_style(self) -> None:
        if self._active:
            self.setStyleSheet(
                "QPushButton { background-color: #1D1E23; border: 1px solid #2C2E37; border-radius: 7px; }"
            )
            self._dot.setStyleSheet("background-color: #10B981; border-radius: 3px; border: none;")
            self._lbl.setStyleSheet(
                "color: #FAFAFA; font-size: 12px; font-weight: 600; background: transparent; border: none;"
            )
        else:
            self.setStyleSheet(
                "QPushButton { background-color: transparent; border: 1px solid transparent; border-radius: 7px; }"
                "QPushButton:hover { background-color: #18181D; }"
            )
            self._dot.setStyleSheet("background-color: #52525B; border-radius: 3px; border: none;")
            self._lbl.setStyleSheet(
                "color: #A1A1AA; font-size: 12px; font-weight: 500; background: transparent; border: none;"
            )


class FlatSwitch(QCheckBox):
    """Monochrome / Emerald Studio 2.0 toggle switch compatible with QCheckBox API."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(24)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        return QSize(34 + 10 + text_w + 8, max(24, fm.height() + 6))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            track_w, track_h = 34, 18
            y = (self.height() - track_h) // 2
            checked = self.isChecked()

            if checked:
                track_col = QColor("#10B981")
                border_col = QColor("#34D399")
                knob_col = QColor("#041710")
            else:
                track_col = QColor("#24242B")
                border_col = QColor("#32323B")
                knob_col = QColor("#A1A1AA")

            p.setBrush(track_col)
            p.setPen(QPen(border_col, 1))
            p.drawRoundedRect(1, y, track_w, track_h, track_h / 2.0, track_h / 2.0)

            knob_d = 12
            knob_x = (track_w - knob_d - 2) if checked else 4
            knob_y = y + (track_h - knob_d) // 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(knob_col)
            p.drawEllipse(knob_x, knob_y, knob_d, knob_d)

            text_col = (
                QColor("#FAFAFA")
                if (self.isEnabled() and checked)
                else (QColor("#A1A1AA") if self.isEnabled() else QColor("#52525B"))
            )
            p.setPen(text_col)
            p.setFont(self.font())
            text_rect = QRect(track_w + 10, 0, self.width() - track_w - 10, self.height())
            p.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self.text(),
            )
        finally:
            p.end()


class FlatComboBox(QComboBox):
    """Flat Studio 2.0 dropdown with crisp vector chevron drawn identically on all platforms."""

    def __init__(self, parent: Optional[QWidget] = None, on_before_popup=None) -> None:
        super().__init__(parent)
        self._on_before_popup = on_before_popup

    def showPopup(self) -> None:
        if callable(self._on_before_popup):
            try:
                self._on_before_popup()
            except Exception:
                pass
        super().showPopup()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            col = QColor("#A1A1AA") if self.isEnabled() else QColor("#52525B")
            pen = QPen(
                col,
                1.5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(pen)
            cx = self.width() - 14
            cy = self.height() // 2
            p.drawLine(QPointF(cx - 3.6, cy - 1.8), QPointF(cx, cy + 2.0))
            p.drawLine(QPointF(cx, cy + 2.0), QPointF(cx + 3.6, cy - 1.8))
        finally:
            p.end()


class TelemetryCard(QFrame):
    """Studio 2.0 flat KPI / Telemetry metric card."""

    def __init__(
        self,
        title: str,
        badge_text: str,
        initial_val: str,
        sub_text: str,
        accent_hex: str = "#10B981",
        initial_pct: int = 35,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.accent_hex = accent_hex
        self.setObjectName("telemetryCard")
        self.setStyleSheet(
            """
            QFrame#telemetryCard {
                background-color: #141417;
                border: 1px solid #24242A;
                border-radius: 9px;
            }
            QFrame#telemetryCard QLabel {
                background-color: transparent;
                border: none;
            }
            """
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 11, 13, 11)
        lay.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.setSpacing(6)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            "color: #71717A; font-size: 10px; font-weight: 700; letter-spacing: 0.7px;"
        )
        hdr.addWidget(self.lbl_title)

        self.lbl_badge = QLabel(badge_text)
        self.lbl_badge.setStyleSheet(
            f"color: {accent_hex}; font-size: 10px; font-weight: 700;"
        )
        hdr.addWidget(self.lbl_badge, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(hdr)

        self.lbl_val = QLabel(initial_val)
        self.lbl_val.setStyleSheet(
            "color: #FAFAFA; font-size: 19px; font-weight: 700; letter-spacing: -0.4px;"
        )
        lay.addWidget(self.lbl_val)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(max(4, min(100, int(initial_pct))))
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(3)
        self.bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: none;
                background-color: #24242A;
                border-radius: 1px;
            }}
            QProgressBar::chunk {{
                background-color: {accent_hex};
                border-radius: 1px;
            }}
            """
        )
        lay.addWidget(self.bar)

        self.lbl_sub = QLabel(sub_text)
        self.lbl_sub.setStyleSheet("color: #71717A; font-size: 11px; font-weight: 500;")
        lay.addWidget(self.lbl_sub)

    def set_title(self, title: str) -> None:
        self.lbl_title.setText(title)

    def set_metric(
        self,
        val_text: str,
        sub_text: Optional[str] = None,
        badge_text: Optional[str] = None,
        bar_pct: Optional[int] = None,
    ) -> None:
        self.lbl_val.setText(val_text)
        if sub_text is not None:
            self.lbl_sub.setText(sub_text)
        if badge_text is not None:
            self.lbl_badge.setText(badge_text)
        if bar_pct is not None:
            self.bar.setValue(max(4, min(100, int(round(bar_pct)))))


class DualWaveformMeter(QWidget):
    """
    Studio 2.0 Dual-Channel Live Canvas Waveform Meter with subtle VAD glow:
      - Top trace: Microphone ('You') in Emerald Mint #10B981
      - Bottom trace: System Loopback ('Remote') in Sky #38BDF8
    """

    def __init__(self, bars: int = 24, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bars = max(12, bars)
        self._mic_history: deque[float] = deque([0.0] * self._bars, maxlen=self._bars)
        self._sys_history: deque[float] = deque([0.0] * self._bars, maxlen=self._bars)
        self._mic_val = 0.0
        self._sys_val = 0.0
        self.setFixedSize(164, 34)
        self.setToolTip("Dual-channel live audio waveform (Emerald: Mic · Sky: Remote Loopback)")

    def set_level(self, speaker: str, level: float) -> None:
        clamped = max(0.0, min(1.0, float(level)))
        is_mic = speaker in ("You", "Sen", "Mic")
        if is_mic:
            self._mic_val = max(clamped, self._mic_val * 0.65)
            self._mic_history.append(self._mic_val)
        else:
            self._sys_val = max(clamped, self._sys_val * 0.65)
            self._sys_history.append(self._sys_val)
        self.update()

    def seed_demo_levels(self) -> None:
        """Populate realistic dual-channel wave heights for screenshot previews."""
        mic_vals = [
            0.12, 0.20, 0.35, 0.58, 0.42, 0.76, 0.64, 0.32, 0.18, 0.25, 0.48, 0.82,
            0.69, 0.50, 0.28, 0.15, 0.22, 0.45, 0.62, 0.38, 0.25, 0.40, 0.55, 0.32,
        ]
        sys_vals = [
            0.08, 0.14, 0.18, 0.22, 0.45, 0.68, 0.72, 0.55, 0.38, 0.20, 0.12, 0.16,
            0.28, 0.52, 0.78, 0.64, 0.44, 0.30, 0.18, 0.24, 0.48, 0.62, 0.35, 0.22,
        ]
        self._mic_history = deque(mic_vals[-self._bars :], maxlen=self._bars)
        self._sys_history = deque(sys_vals[-self._bars :], maxlen=self._bars)
        self._mic_val = self._mic_history[-1]
        self._sys_val = self._sys_history[-1]
        self.update()

    def reset(self) -> None:
        self._mic_val = 0.0
        self._sys_val = 0.0
        self._mic_history = deque([0.0] * self._bars, maxlen=self._bars)
        self._sys_history = deque([0.0] * self._bars, maxlen=self._bars)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()

            # Flat studio housing with subtle VAD active glow border
            vad_active = (self._mic_val > 0.16) or (self._sys_val > 0.16)
            border_col = QColor("#1D4E3D") if vad_active else QColor("#24242A")
            p.setBrush(QColor("#111114"))
            p.setPen(QPen(border_col, 1.0))
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), 7.0, 7.0)

            # Center hairline divider
            mid_y = h / 2.0
            p.setPen(QPen(QColor("#1E1E24"), 1.0))
            p.drawLine(QPointF(8.0, mid_y), QPointF(w - 8.0, mid_y))

            pad_x = 8.0
            usable_w = w - 2 * pad_x
            step = usable_w / max(1, self._bars)
            bar_w = max(2.2, step * 0.56)
            max_half_h = (h / 2.0) - 4.5

            p.setPen(Qt.PenStyle.NoPen)
            for idx in range(self._bars):
                x = pad_x + idx * step + (step - bar_w) / 2.0
                mv = self._mic_history[idx]
                sv = self._sys_history[idx]

                # Top channel (Mic — Emerald Mint)
                mh = max(2.0, mv * max_half_h)
                m_alpha = int(95 + 160 * mv)
                p.setBrush(QColor(16, 185, 129, m_alpha))
                p.drawRoundedRect(QRectF(x, mid_y - mh - 1.0, bar_w, mh), 1.2, 1.2)

                # Bottom channel (Remote — Sky)
                sh = max(2.0, sv * max_half_h)
                s_alpha = int(95 + 160 * sv)
                p.setBrush(QColor(56, 189, 248, s_alpha))
                p.drawRoundedRect(QRectF(x, mid_y + 1.0, bar_w, sh), 1.2, 1.2)
        finally:
            p.end()
