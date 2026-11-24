"""Offscreen PyQt6 Studio 2.0 UI tests for MainWindow, notes race safety, tabs, i18n, demo, and tags."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from localminutes.models import AppSettings
from localminutes.ui.main_window import MainWindow
from localminutes.ui.theme import build_studio_qss


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(build_studio_qss())
    return app


@pytest.fixture()
def studio_window(qapp: QApplication, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALMINUTES_DATA_DIR", str(tmp_path))
    win = MainWindow(db_path=tmp_path / "ui_test.db", auto_check_updates=False)
    win.resize(1240, 730)
    qapp.processEvents()
    try:
        yield win
    finally:
        win._force_quit = True
        win.close()
        qapp.processEvents()


def test_notes_debounce_flush_race_safety_on_meeting_switch(
    studio_window: MainWindow, qapp: QApplication
) -> None:
    """Unsaved debounced notes on Meeting A must flush to A (never leak into Meeting B) on instant switch."""
    win = studio_window
    meeting_a = win._db.create_meeting(title="Meeting Alpha", notes="Initial alpha note")
    meeting_b = win._db.create_meeting(title="Meeting Beta", notes="Initial beta note")
    assert meeting_a.id is not None and meeting_b.id is not None

    win._load_meeting(meeting_a.id)
    assert win._current_meeting is not None and win._current_meeting.id == meeting_a.id

    # Simulate user typing into Notes tab — debounce timer becomes active (450ms pending)
    win._summary_panel._notes_edit.setPlainText("CRITICAL UNSAVED ALPHA NOTE")
    assert win._summary_panel._notes_debounce.isActive() is True
    assert win._summary_panel._notes_dirty is True

    # Immediately switch to Meeting B BEFORE the 450ms debounce timer fires
    win._load_meeting(meeting_b.id)
    qapp.processEvents()

    assert win._summary_panel._notes_debounce.isActive() is False
    assert win._current_meeting.id == meeting_b.id
    assert win._summary_panel._notes_edit.toPlainText() == "Initial beta note"

    # Verify DB persisted Alpha's unsaved notes to Alpha and left Beta untouched
    reloaded_a = win._db.get_meeting(meeting_a.id)
    reloaded_b = win._db.get_meeting(meeting_b.id)
    assert reloaded_a is not None and reloaded_a.notes == "CRITICAL UNSAVED ALPHA NOTE"
    assert reloaded_b is not None and reloaded_b.notes == "Initial beta note"


def test_workspace_views_and_intelligence_dock_tabs(
    studio_window: MainWindow, qapp: QApplication
) -> None:
    win = studio_window

    # 3 Workspace views: Studio (0), Tasks & Insights Hub (1), Settings & Telemetry (2)
    for idx in (0, 1, 2, 0):
        win.switch_view(idx)
        qapp.processEvents()
        assert win._stack.currentIndex() == idx

    # 4 Intelligence Dock tabs: Summary (0), Notes (1), Ask AI (2), Insights (3)
    assert win._summary_panel._tabs.count() == 4
    for tab_idx in range(4):
        win._summary_panel._tabs.setCurrentIndex(tab_idx)
        qapp.processEvents()
        assert win._summary_panel._tabs.currentIndex() == tab_idx


def test_runtime_tr_en_i18n_switching(studio_window: MainWindow, qapp: QApplication) -> None:
    win = studio_window
    assert win._i18n.lang == "en"
    assert win._record_btn.text() == "Record"
    assert win._summary_panel._tabs.tabText(0) == "Summary"

    win._on_language_changed("tr")
    qapp.processEvents()
    assert win._i18n.lang == "tr"
    assert win._record_btn.text() == "Kaydet"
    assert win._summary_panel._tabs.tabText(0) == "Özet"
    assert win._summary_panel._tabs.tabText(2) == "Toplantıya Sor"

    win._on_language_changed("en")
    qapp.processEvents()
    assert win._i18n.lang == "en"
    assert win._record_btn.text() == "Record"
    assert win._summary_panel._tabs.tabText(3) == "Insights"


def test_demo_meeting_loader_and_tags_ui(studio_window: MainWindow, qapp: QApplication) -> None:
    win = studio_window
    demo = win.load_demo_meeting()
    qapp.processEvents()

    assert demo.id is not None
    assert win._current_meeting is not None and win._current_meeting.id == demo.id
    assert len(demo.segments) == 7
    assert win._transcript_view._list.count() == 7
    assert win._sidebar.btn_nav_tasks._badge.text() == "2"  # 2 open action items in demo

    # Add a new tag via tag input box (with leading '#' stripped)
    win._tag_input.setText("#q4-roadmap")
    win._on_add_tag()
    qapp.processEvents()
    assert "q4-roadmap" in win._current_meeting.tags
    assert win._tags_container.count() == len(win._current_meeting.tags)

    # Adding duplicate tag is a no-op
    prev_len = len(win._current_meeting.tags)
    win._tag_input.setText("q4-roadmap")
    win._on_add_tag()
    assert len(win._current_meeting.tags) == prev_len

    # Remove tag and confirm DB persistence
    win._remove_tag("q4-roadmap")
    qapp.processEvents()
    assert "q4-roadmap" not in win._current_meeting.tags
    reloaded = win._db.get_meeting(demo.id)
    assert reloaded is not None and "q4-roadmap" not in reloaded.tags


def test_air_gapped_mode_blocks_update_check_in_ui(
    studio_window: MainWindow, qapp: QApplication
) -> None:
    win = studio_window
    win._on_settings_saved(AppSettings(air_gapped_mode=True))
    qapp.processEvents()

    assert win._status_pill.property("state") == "airgap"
    win._check_updates_async()
    qapp.processEvents()
    assert win._update_thread is None
    assert "Air-Gapped" in win._settings_view.lbl_diag_status.text()
