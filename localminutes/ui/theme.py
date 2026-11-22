"""Modern dark studio stylesheet for LocalMinutes."""

STUDIO_DARK_QSS = """
QMainWindow, QDialog {
    background-color: #0f1117;
    color: #e6edf3;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}

QWidget {
    color: #e6edf3;
}

QSplitter::handle {
    background-color: #1f2430;
    width: 2px;
    height: 2px;
}

QFrame#TopBar {
    background-color: #151922;
    border-bottom: 1px solid #262c3a;
}

QFrame#Card, QGroupBox {
    background-color: #161b26;
    border: 1px solid #262c3a;
    border-radius: 10px;
}

QGroupBox {
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
    color: #9fb0c8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}

QLabel#SectionTitle {
    font-size: 14px;
    font-weight: 700;
    color: #f0f6fc;
}

QLabel#MutedLabel {
    color: #8b949e;
    font-size: 12px;
}

QLabel#TimerLabel {
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 16px;
    font-weight: 700;
    color: #f0f6fc;
    background-color: #1d2330;
    border: 1px solid #2d3648;
    border-radius: 8px;
    padding: 5px 12px;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #121620;
    color: #e6edf3;
    border: 1px solid #2b3242;
    border-radius: 7px;
    padding: 6px 10px;
    selection-background-color: #2f81f7;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #4c8dff;
}

QLineEdit#MeetingTitleInput {
    background-color: transparent;
    border: 1px solid transparent;
    font-size: 16px;
    font-weight: 700;
    padding: 4px 8px;
}

QLineEdit#MeetingTitleInput:hover, QLineEdit#MeetingTitleInput:focus {
    background-color: #1c2230;
    border: 1px solid #303a4d;
}

QPushButton {
    background-color: #1e2533;
    color: #e6edf3;
    border: 1px solid #30394b;
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #283144;
    border-color: #414e66;
}

QPushButton:pressed {
    background-color: #1a202d;
}

QPushButton:disabled {
    background-color: #171b24;
    color: #5b6577;
    border-color: #232836;
}

QPushButton#RecordButton {
    background-color: #d9383a;
    border: 1px solid #f05252;
    color: #ffffff;
    padding: 8px 18px;
}

QPushButton#RecordButton:hover {
    background-color: #e5484d;
}

QPushButton#StopButton {
    background-color: #2c3548;
    border: 1px solid #4c5a75;
    color: #ffffff;
}

QPushButton#PrimaryButton {
    background-color: #2563eb;
    border: 1px solid #3b82f6;
    color: #ffffff;
}

QPushButton#PrimaryButton:hover {
    background-color: #3b82f6;
}

QPushButton#ExportButton {
    background-color: #19202d;
    border: 1px solid #2b3648;
    padding: 5px 10px;
    font-size: 12px;
}

QPushButton#ExportButton:hover {
    background-color: #243044;
    border-color: #4c8dff;
}

QListWidget {
    background-color: #121620;
    border: 1px solid #242a38;
    border-radius: 8px;
    padding: 4px;
    outline: 0;
}

QListWidget::item {
    padding: 8px 10px;
    border-radius: 6px;
    margin-bottom: 2px;
}

QListWidget::item:hover {
    background-color: #1b2231;
}

QListWidget::item:selected {
    background-color: #23324d;
    border: 1px solid #3b82f6;
    color: #ffffff;
}

QTextBrowser, QPlainTextEdit {
    background-color: #121620;
    color: #e6edf3;
    border: 1px solid #242a38;
    border-radius: 8px;
    padding: 10px;
    selection-background-color: #2f81f7;
}

QTabWidget::pane {
    border: 1px solid #262c3a;
    border-radius: 8px;
    background-color: #141822;
}

QTabBar::tab {
    background-color: #171c28;
    color: #9fb0c8;
    padding: 8px 16px;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    margin-right: 4px;
}

QTabBar::tab:selected {
    background-color: #222a3a;
    color: #ffffff;
    font-weight: 600;
}

QStatusBar {
    background-color: #131720;
    border-top: 1px solid #232938;
    color: #9fb0c8;
}

QProgressBar {
    background-color: #121620;
    border: 1px solid #262c3a;
    border-radius: 4px;
    text-align: center;
    height: 10px;
}

QProgressBar::chunk {
    border-radius: 3px;
}

QScrollBar:vertical {
    background: #121620;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: #2c3548;
    border-radius: 4px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #3d4a64;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""
