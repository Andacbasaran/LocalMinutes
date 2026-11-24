"""Studio 2.0 (Monolith / Studio Graphite) stylesheet for LocalMinutes v1.0.0."""

from __future__ import annotations

from localminutes.hardware import get_mono_font_family, get_ui_font_family

# Signature Palette Constants
BG_CANVAS = "#0A0A0C"
BG_SIDEBAR = "#111113"
BG_CARD = "#141417"
BG_ELEVATED = "#1B1B21"
BORDER_SUBTLE = "#24242A"
BORDER_HOVER = "#383842"
INK_PRIMARY = "#FAFAFA"
INK_SECONDARY = "#A1A1AA"
INK_MUTED = "#71717A"
ACCENT_EMERALD = "#10B981"
ACCENT_EMERALD_SOFT = "rgba(16, 185, 129, 0.14)"
ACCENT_SKY = "#38BDF8"
ACCENT_SKY_SOFT = "rgba(56, 189, 248, 0.14)"
ACCENT_ROSE = "#E11D48"
ACCENT_AMBER = "#F59E0B"


def build_studio_qss() -> str:
    """Build cross-platform Studio 2.0 Fusion dark QSS with OS-native fonts."""
    ui_font = get_ui_font_family()
    mono_font = get_mono_font_family()
    return f"""
QMainWindow, QDialog, QWidget#centralWidget {{
    background-color: {BG_CANVAS};
    color: {INK_PRIMARY};
    font-family: "{ui_font}", "Segoe UI", "Inter", -apple-system, sans-serif;
    font-size: 13px;
}}

QWidget {{
    color: {INK_PRIMARY};
    font-family: "{ui_font}", "Segoe UI", "Inter", -apple-system, sans-serif;
}}

QLabel {{
    background-color: transparent;
    color: #E4E4E7;
}}

QFrame#SidebarRail {{
    background-color: {BG_SIDEBAR};
    border: none;
    border-right: 1px solid #222227;
}}

QFrame#CommandHeader {{
    background-color: #0E0E11;
    border-bottom: 1px solid {BORDER_SUBTLE};
}}

QFrame#StudioCard, QFrame#Card {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 10px;
}}

QFrame#PrivacyCard {{
    background-color: #0F1715;
    border: 1px solid #1C382E;
    border-radius: 9px;
}}

QSplitter::handle {{
    background-color: #1D1D23;
    width: 1px;
    height: 1px;
}}

QLabel#SectionTitle {{
    font-size: 14px;
    font-weight: 700;
    color: {INK_PRIMARY};
    letter-spacing: -0.2px;
}}

QLabel#PageTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {INK_PRIMARY};
    letter-spacing: -0.3px;
}}

QLabel#EyebrowLabel {{
    color: {INK_MUTED};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.9px;
}}

QLabel#MutedLabel {{
    color: {INK_SECONDARY};
    font-size: 12px;
}}

QLabel#TimerLabel {{
    font-family: "{mono_font}", "Cascadia Mono", "Consolas", monospace;
    font-size: 14px;
    font-weight: 700;
    color: {INK_PRIMARY};
    background-color: {BG_CARD};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 7px;
    padding: 5px 10px;
}}

QLabel#StatusPill {{
    background-color: rgba(16, 185, 129, 0.14);
    color: #34D399;
    border: 1px solid rgba(16, 185, 129, 0.35);
    border-radius: 10px;
    padding: 2px 9px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}

QLabel#StatusPill[state="recording"] {{
    background-color: rgba(225, 29, 72, 0.18);
    color: #FB7185;
    border: 1px solid rgba(225, 29, 72, 0.45);
}}

QLabel#StatusPill[state="paused"] {{
    background-color: rgba(245, 158, 11, 0.16);
    color: #FBBF24;
    border: 1px solid rgba(245, 158, 11, 0.40);
}}

QLabel#StatusPill[state="airgap"] {{
    background-color: rgba(16, 185, 129, 0.22);
    color: #6EE7B7;
    border: 1px solid rgba(16, 185, 129, 0.55);
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {BG_CARD};
    color: {INK_PRIMARY};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {ACCENT_EMERALD};
    selection-color: #051A12;
}}

QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {BORDER_HOVER};
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT_EMERALD};
}}

QLineEdit#MeetingTitleInput {{
    background-color: transparent;
    border: 1px solid transparent;
    font-size: 16px;
    font-weight: 700;
    color: {INK_PRIMARY};
    padding: 3px 6px;
    border-radius: 7px;
}}

QLineEdit#MeetingTitleInput:hover, QLineEdit#MeetingTitleInput:focus {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER_SUBTLE};
}}

QComboBox {{
    padding: 6px 26px 6px 10px;
    min-height: 20px;
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: #16161B;
    color: #F4F4F5;
    selection-background-color: #24242D;
    selection-color: #FFFFFF;
    border: 1px solid #32323D;
    outline: none;
    padding: 4px;
}}

QPushButton {{
    background-color: {BG_ELEVATED};
    color: #E4E4E7;
    border: 1px solid #2B2B34;
    border-radius: 7px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: #24242D;
    border-color: #3F3F4A;
    color: #FFFFFF;
}}

QPushButton:pressed {{
    background-color: #16161B;
}}

QPushButton:disabled {{
    background-color: #121216;
    color: #52525B;
    border-color: #1E1E24;
}}

QPushButton#PrimaryButton {{
    background-color: {ACCENT_EMERALD};
    border: 1px solid #34D399;
    color: #041710;
    font-weight: 700;
}}

QPushButton#PrimaryButton:hover {{
    background-color: #34D399;
    border-color: #6EE7B7;
    color: #03130D;
}}

QPushButton#PrimaryButton:disabled {{
    background-color: #163228;
    border-color: #1D4436;
    color: #5E8777;
}}

QPushButton#RecordButton {{
    background-color: {ACCENT_ROSE};
    border: 1px solid #F43F5E;
    color: #FFFFFF;
    padding: 7px 14px;
    font-weight: 700;
}}

QPushButton#RecordButton:hover {{
    background-color: #F43F5E;
}}

QPushButton#StopButton {{
    background-color: #272730;
    border: 1px solid #3F3F4D;
    color: #FAFAFA;
}}

QPushButton#GhostButton, QPushButton#ExportButton {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER_SUBTLE};
    color: #D4D4D8;
    padding: 5px 10px;
    font-size: 11.5px;
}}

QPushButton#GhostButton:hover, QPushButton#ExportButton:hover {{
    background-color: #1F1F26;
    border-color: #3E3E4B;
    color: #FAFAFA;
}}

QPushButton#FilterPill {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER_SUBTLE};
    color: {INK_SECONDARY};
    border-radius: 12px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
}}

QPushButton#FilterPill:hover {{
    border-color: #3E3E4B;
    color: {INK_PRIMARY};
}}

QPushButton#FilterPill:checked {{
    background-color: rgba(16, 185, 129, 0.16);
    border-color: {ACCENT_EMERALD};
    color: #34D399;
}}

QPushButton#DangerButton {{
    background-color: rgba(225, 29, 72, 0.12);
    border: 1px solid rgba(225, 29, 72, 0.35);
    color: #FDA4AF;
    padding: 5px 10px;
}}

QPushButton#DangerButton:hover {{
    background-color: rgba(225, 29, 72, 0.24);
    color: #FFFFFF;
}}

QListWidget {{
    background-color: transparent;
    border: none;
    outline: 0;
    color: #E4E4E7;
}}

QListWidget#ArchiveList {{
    background-color: transparent;
    border: none;
    padding: 0px;
}}

QListWidget#ArchiveList::item {{
    padding: 7px 9px;
    border-radius: 7px;
    margin-bottom: 3px;
    border: 1px solid transparent;
    color: #D4D4D8;
}}

QListWidget#ArchiveList::item:hover {{
    background-color: #19191F;
}}

QListWidget#ArchiveList::item:selected {{
    background-color: #1C2320;
    border: 1px solid rgba(16, 185, 129, 0.42);
    color: #FAFAFA;
}}

QListWidget#TranscriptList {{
    background-color: #0D0D10;
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 9px;
    padding: 6px;
}}

QListWidget#TranscriptList::item {{
    background: transparent;
    border: none;
    padding: 0px;
    margin-bottom: 4px;
}}

QListWidget#TranscriptList::item:selected {{
    background: transparent;
}}

QTextBrowser, QPlainTextEdit {{
    background-color: #0E0E11;
    color: #E4E4E7;
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 8px;
    padding: 10px;
    selection-background-color: {ACCENT_EMERALD};
    selection-color: #041710;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 9px;
    background-color: {BG_CARD};
    top: -1px;
}}

QTabBar::tab {{
    background-color: #101014;
    color: {INK_SECONDARY};
    border: 1px solid transparent;
    padding: 5px 7px;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    margin-right: 1px;
    font-size: 11px;
    font-weight: 600;
}}

QTabBar::tab:hover {{
    color: {INK_PRIMARY};
    background-color: #17171D;
}}

QTabBar::tab:selected {{
    background-color: {BG_CARD};
    color: {INK_PRIMARY};
    border: 1px solid {BORDER_SUBTLE};
    border-bottom: 2px solid {ACCENT_EMERALD};
}}

QMenu {{
    background-color: #16161B;
    color: #FAFAFA;
    border: 1px solid #2E2E38;
    border-radius: 8px;
    padding: 5px;
}}

QMenu::item {{
    padding: 6px 16px;
    border-radius: 5px;
}}

QMenu::item:selected {{
    background-color: #23232D;
    color: #FFFFFF;
}}

QMenu::separator {{
    height: 1px;
    background: #262630;
    margin: 4px 6px;
}}

QStatusBar {{
    background-color: #0D0D10;
    border-top: 1px solid {BORDER_SUBTLE};
    color: {INK_SECONDARY};
    font-size: 11.5px;
}}

QProgressBar {{
    background-color: #18181E;
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 4px;
    text-align: center;
    height: 8px;
}}

QProgressBar::chunk {{
    background-color: {ACCENT_EMERALD};
    border-radius: 3px;
}}

QScrollArea {{
    background-color: transparent;
    border: none;
}}

QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}

QCheckBox {{
    spacing: 8px;
    color: #E4E4E7;
    background: transparent;
}}

QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1.5px solid #3F3F4A;
    background-color: #111114;
}}

QCheckBox::indicator:hover {{
    border-color: {ACCENT_EMERALD};
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT_EMERALD};
    border: 1.5px solid #34D399;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 2px 0;
}}

QScrollBar::handle:vertical {{
    background: #2C2C35;
    border-radius: 3px;
    min-height: 26px;
}}

QScrollBar::handle:vertical:hover {{
    background: #464654;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
}}

QScrollBar::handle:horizontal {{
    background: #2C2C35;
    border-radius: 3px;
    min-width: 26px;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
"""


STUDIO_DARK_QSS = build_studio_qss()
