"""Application bootstrap for LocalMinutes v1.0.0 Studio 2.0 (Fusion, single-instance lock & crash log)."""

from __future__ import annotations

import logging
import os
import sys
import traceback
from datetime import datetime
from typing import Optional

from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from localminutes import __app_name__, __version__
from localminutes.config import get_crash_log_path
from localminutes.ui.main_window import MainWindow
from localminutes.ui.studio_widgets import create_app_icon
from localminutes.ui.theme import build_studio_qss

_SINGLE_INSTANCE_KEY = "com.andacbasaran.localminutes.v1"


def install_crash_logger() -> None:
    """Install a global sys.excepthook that appends uncaught tracebacks to crash.log."""
    prev_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb) -> None:
        try:
            log_path = get_crash_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().isoformat(timespec="seconds")
            body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n=== Crash {stamp} ({__app_name__} v{__version__}) ===\n{body}\n")
        except Exception:
            pass
        prev_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook


def _acquire_single_instance(window_activator) -> Optional[QLocalServer]:
    """Ensure only one interactive desktop instance runs; raise existing window if already open."""
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen" or "--allow-multi" in sys.argv:
        return None

    probe = QLocalSocket()
    probe.connectToServer(_SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(200):
        probe.write(b"SHOW")
        probe.flush()
        probe.waitForBytesWritten(200)
        probe.disconnectFromServer()
        return None

    QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    if not server.listen(_SINGLE_INSTANCE_KEY):
        return server

    def _on_new_conn() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.waitForReadyRead(100)
            conn.disconnectFromServer()
        window_activator()

    server.newConnection.connect(_on_new_conn)
    return server


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    install_crash_logger()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(create_app_icon())
    app.setStyleSheet(build_studio_qss())

    # If another interactive instance is already alive, activate it and exit cleanly
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen" and "--allow-multi" not in sys.argv:
        probe = QLocalSocket()
        probe.connectToServer(_SINGLE_INSTANCE_KEY)
        if probe.waitForConnected(200):
            probe.write(b"SHOW")
            probe.flush()
            probe.waitForBytesWritten(200)
            probe.disconnectFromServer()
            return 0

    window = MainWindow()
    server = _acquire_single_instance(
        lambda: (window.showNormal(), window.raise_(), window.activateWindow())
    )
    window.show()

    exit_code = app.exec()
    if server is not None:
        server.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
