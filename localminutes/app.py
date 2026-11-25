"""Application bootstrap for LocalMinutes v1.0.0 Studio 2.0 (Fusion, single-instance lock & crash log)."""

from __future__ import annotations

import getpass
import hashlib
import logging
import os
import sys
import threading
import traceback
from datetime import datetime
from typing import Callable, Optional

from localminutes import __app_name__, __version__
from localminutes.config import get_crash_log_path, load_settings
from localminutes.hardware import (
    apply_thread_env_defaults,
    compute_runtime_tuning,
    detect_hardware_profile,
)

_MAX_CRASH_LOG_BYTES = 1024 * 1024  # 1 MiB cap for crash.log
_CRASH_LOG_LOCK = threading.Lock()


def _build_single_instance_key() -> str:
    """Build a per-user IPC socket name so multi-user machines never collide."""
    if hasattr(os, "getuid"):
        user_tag = str(os.getuid())
    else:
        raw_user = getpass.getuser() or os.environ.get("USERNAME") or "default"
        user_tag = hashlib.sha256(raw_user.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"com.andacbasaran.localminutes.v1.{user_tag}"


_SINGLE_INSTANCE_KEY = _build_single_instance_key()


def _configure_early_runtime_env() -> None:
    """Apply CPU thread env defaults BEFORE importing MainWindow, numpy, scipy, or ctranslate2."""
    try:
        settings = load_settings()
        hw = detect_hardware_profile(query_ct2=False)
        tuning = compute_runtime_tuning(
            hw,
            requested_profile=settings.performance_profile,
            preferred_compute_type=settings.whisper_compute_type,
        )
        apply_thread_env_defaults(tuning)
    except Exception:
        pass


def _append_crash_record(exc_type, exc_value, exc_tb, context: str = "") -> None:
    """Write a bounded crash traceback entry to crash.log."""
    with _CRASH_LOG_LOCK:
        try:
            log_path = get_crash_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().isoformat(timespec="seconds")
            ctx = f" [{context}]" if context else ""
            body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            entry = f"\n=== Crash {stamp}{ctx} ({__app_name__} v{__version__}) ===\n{body}\n"

            if log_path.exists():
                try:
                    size = log_path.stat().st_size
                    if size + len(entry.encode("utf-8", errors="replace")) > _MAX_CRASH_LOG_BYTES:
                        keep_bytes = max(0, (_MAX_CRASH_LOG_BYTES // 2) - len(entry.encode("utf-8", errors="replace")))
                        existing = log_path.read_bytes()
                        trimmed = existing[-keep_bytes:] if keep_bytes > 0 else b""
                        log_path.write_bytes(trimmed)
                except OSError:
                    pass

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry)
            if os.name == "posix":
                try:
                    os.chmod(log_path, 0o600)
                except OSError:
                    pass
        except Exception:
            pass


def install_crash_logger() -> None:
    """Install global sys.excepthook and threading.excepthook appending bounded tracebacks to crash.log."""
    prev_sys_hook = sys.excepthook
    prev_thread_hook = getattr(threading, "excepthook", None)

    def _sys_hook(exc_type, exc_value, exc_tb) -> None:
        _append_crash_record(exc_type, exc_value, exc_tb)
        prev_sys_hook(exc_type, exc_value, exc_tb)

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        thread_name = getattr(args.thread, "name", "worker") if args.thread else "worker"
        _append_crash_record(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            context=f"thread:{thread_name}",
        )
        if prev_thread_hook is not None:
            prev_thread_hook(args)

    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook


def _signal_existing_instance(key: str) -> bool:
    """Connect to an already-running instance and ask it to raise its window."""
    from PyQt6.QtNetwork import QLocalSocket

    probe = QLocalSocket()
    probe.connectToServer(key)
    if probe.waitForConnected(200):
        probe.write(b"SHOW")
        probe.flush()
        probe.waitForBytesWritten(200)
        probe.disconnectFromServer()
        return True
    return False


def _acquire_single_instance(
    window_activator: Callable[[], None],
    key: Optional[str] = None,
) -> tuple[bool, Optional[object]]:
    """
    Ensure only one interactive desktop instance runs per user.
    Returns `(acquired, server)`. If `acquired` is False, an existing instance answered and
    the caller should exit cleanly with code 0.
    """
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen" or "--allow-multi" in sys.argv:
        return (True, None)

    from PyQt6.QtNetwork import QLocalServer

    instance_key = key or _SINGLE_INSTANCE_KEY

    if _signal_existing_instance(instance_key):
        return (False, None)

    server = QLocalServer()
    try:
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    except AttributeError:
        pass

    if not server.listen(instance_key):
        # Could be a stale socket left by a crash OR a concurrent launch racing with us.
        if _signal_existing_instance(instance_key):
            return (False, None)
        QLocalServer.removeServer(instance_key)
        if not server.listen(instance_key):
            if _signal_existing_instance(instance_key):
                return (False, None)
            return (True, None)

    def _on_new_conn() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.waitForReadyRead(100)
            conn.disconnectFromServer()
        window_activator()

    server.newConnection.connect(_on_new_conn)
    return (True, server)


def main() -> int:
    # Apply BLAS/OMP/CTranslate2 thread env limits BEFORE loading numpy, scipy, ctranslate2, or UI.
    _configure_early_runtime_env()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    install_crash_logger()

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)

    window_holder: list[Optional[object]] = [None]

    def _activate_window() -> None:
        win = window_holder[0]
        if win is not None:
            win.showNormal()  # type: ignore[attr-defined]
            win.raise_()  # type: ignore[attr-defined]
            win.activateWindow()  # type: ignore[attr-defined]

    # Acquire single-instance lock ONCE before instantiating MainWindow/SQLite/Whisper.
    acquired, server = _acquire_single_instance(_activate_window)
    if not acquired:
        return 0

    from localminutes.ui.main_window import MainWindow
    from localminutes.ui.studio_widgets import create_app_icon
    from localminutes.ui.theme import build_studio_qss

    app.setWindowIcon(create_app_icon())
    app.setStyleSheet(build_studio_qss())

    window = MainWindow()
    window_holder[0] = window
    window.show()

    exit_code = app.exec()
    if server is not None:
        server.close()  # type: ignore[attr-defined]
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
