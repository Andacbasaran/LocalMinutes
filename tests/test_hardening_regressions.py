"""Regression tests for LocalMinutes P0/P1 privacy, audio, DB, export, and UI fixes."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from localminutes.audio.capture import resample_to_16k_mono
from localminutes.audio.devices import is_virtual_loopback_name
from localminutes.export.exporter import format_markdown, format_vtt, parse_meeting_json
from localminutes.models import AppSettings, Meeting, SummaryResult, TranscriptSegment
from localminutes.storage.database import MeetingDatabase, _extract_assignee
from localminutes.summarization.qa import retrieve_bm25_citations
from localminutes.transcription.engine import WhisperEngine, get_cached_model_info
from localminutes.ui.widgets.transcript_view import _SegmentCard
from localminutes.updater import (
    UpdateInfo,
    download_update_asset,
    is_newer_version,
    select_platform_asset,
)


def test_air_gapped_whisper_engine_and_partial_cache_rejection(tmp_path: Path) -> None:
    eng = WhisperEngine(model_size="small", local_files_only=True)
    assert eng.local_files_only is True

    # A directory with only metadata/lock files (no model.bin) must NOT be reported as cached
    partial = tmp_path / "models--Systran--faster-whisper-small" / "snapshots" / "abc"
    partial.mkdir(parents=True)
    (partial / "config.json").write_text("{}", encoding="utf-8")
    info = get_cached_model_info(tmp_path)
    assert info["small"]["cached"] is False


def test_updater_fail_closed_and_windows_checksum_selection(tmp_path: Path) -> None:
    assert is_newer_version("1.0.0-rc.2", "1.0.0-rc.1") is True
    assert is_newer_version("1.0.0+build.1", "1.0.0-rc.9") is True

    assets = [
        {
            "name": "LocalMinutes-Setup-v1.1.0-Windows-x64.exe",
            "browser_download_url": "https://github.com/Andacbasaran/LocalMinutes/releases/download/v1.1.0/LocalMinutes-Setup-v1.1.0-Windows-x64.exe",
            "size": 1000,
        },
        {
            "name": "SHA256SUMS-Windows.txt",
            "browser_download_url": "https://github.com/Andacbasaran/LocalMinutes/releases/download/v1.1.0/SHA256SUMS-Windows.txt",
            "size": 100,
        },
        {
            "name": "SHA256SUMS-macOS.txt",
            "browser_download_url": "https://github.com/Andacbasaran/LocalMinutes/releases/download/v1.1.0/SHA256SUMS-macOS.txt",
            "size": 100,
        },
    ]
    _, _, _, win_cs = select_platform_asset(assets, platform_name="win32", machine="AMD64")
    assert win_cs.endswith("SHA256SUMS-Windows.txt")

    info_no_cs = UpdateInfo(
        current_version="1.0.0",
        latest_version="1.1.0",
        is_update_available=True,
        release_url="https://github.com/Andacbasaran/LocalMinutes/releases/tag/v1.1.0",
        asset_name="LocalMinutes-Setup-v1.1.0-Windows-x64.exe",
        asset_url="https://github.com/Andacbasaran/LocalMinutes/releases/download/v1.1.0/LocalMinutes-Setup-v1.1.0-Windows-x64.exe",
        checksum_url="",
    )
    with pytest.raises(RuntimeError, match="SHA-256"):
        download_update_asset(info_no_cs, str(tmp_path))

    info_ok = UpdateInfo(
        current_version="1.0.0",
        latest_version="1.1.0",
        is_update_available=True,
        release_url="https://github.com/Andacbasaran/LocalMinutes/releases/tag/v1.1.0",
        asset_name="LocalMinutes-Setup-v1.1.0-Windows-x64.exe",
        asset_url="https://github.com/Andacbasaran/LocalMinutes/releases/download/v1.1.0/LocalMinutes-Setup-v1.1.0-Windows-x64.exe",
        checksum_url="https://github.com/Andacbasaran/LocalMinutes/releases/download/v1.1.0/SHA256SUMS-Windows.txt",
    )
    asset_resp = MagicMock()
    asset_resp.headers = {"Content-Length": "4"}
    asset_resp.read.side_effect = [b"data", b""]
    asset_resp.__enter__.return_value = asset_resp
    sums_resp = MagicMock()
    sums_resp.__enter__.return_value = BytesIO(b"")
    with patch("localminutes.updater.urllib.request.urlopen", side_effect=[asset_resp, sums_resp]):
        with pytest.raises(RuntimeError, match="SHA-256"):
            download_update_asset(info_ok, str(tmp_path))


def test_turkish_unicode_qa_and_no_short_prefix_pollution() -> None:
    segs = [
        TranscriptSegment(id=1, meeting_id=1, speaker="You", text="İstanbul lansmanı Cuma günü yapılacak.", start_sec=1.0, end_sec=4.0),
        TranscriptSegment(id=2, meeting_id=1, speaker="Remote", text="We are in to re go on it.", start_sec=5.0, end_sec=8.0),
    ]
    tr_hits = retrieve_bm25_citations("istanbul lansman", segs)
    assert tr_hits and tr_hits[0].segment_id == 1

    # Query 'release interview' must NOT falsely match 2-char words 're'/'in'
    en_hits = retrieve_bm25_citations("release interview", segs)
    assert all(h.segment_id != 2 for h in en_hits)


def test_assignee_extraction_word_count_and_like_escape(tmp_path: Path) -> None:
    assert _extract_assignee("https://example.com/pr") == ("", "https://example.com/pr")
    assert _extract_assignee("14:30 standup sync") == ("", "14:30 standup sync")
    assert _extract_assignee("Note: double check deploy") == ("", "Note: double check deploy")
    assert _extract_assignee("Andac: ship release notes") == ("Andac", "ship release notes")

    db = MeetingDatabase(tmp_path / "m.db")
    m = db.create_meeting(title="100% Launch_Plan")
    assert m.id is not None
    db.add_segment(TranscriptSegment(meeting_id=m.id, speaker="You", text="one two three four", start_sec=0.0, end_sec=2.0))
    insights = db.get_archive_insights()
    assert insights["total_words"] == 4
    assert len(db.search_meetings("100%")) == 1
    assert len(db.search_meetings("____")) == 0
    db.close()


def test_exporters_yaml_vtt_sanitization_and_malformed_json() -> None:
    meeting = Meeting(
        id=1,
        title='Q4 "Review"\nevil: true',
        tags=["roadmap", "bad: tag\ninjected"],
        segments=[
            TranscriptSegment(
                meeting_id=1,
                speaker="A>B",
                text="check a < b & c --> next\n\nline2",
                start_sec=0.0,
                end_sec=3.0,
            )
        ],
        summary=SummaryResult(overview="ok"),
    )
    obs = format_markdown(meeting, obsidian_frontmatter=True)
    assert "\nevil: true\n" not in obs.split("---")[1]

    vtt = format_vtt(meeting)
    assert "-->" not in vtt.split("00:00:03.000", 1)[1]
    assert "&lt;" in vtt and "&amp;" in vtt

    parsed = parse_meeting_json(
        '{"title": "Safe", "tags": "not-a-list", "segments": [{"text": "hi", "start_sec": null, "end_sec": "NaN"}], "summary": {"overview": "x", "key_points": null}}'
    )
    assert parsed.title == "Safe"
    assert isinstance(parsed.tags, list)
    assert len(parsed.segments) == 1
    assert parsed.segments[0].start_sec == 0.0


def test_transcript_highlight_does_not_corrupt_html_entities() -> None:
    rendered = _SegmentCard._render_highlighted_html("A & B < C", "amp")
    assert "&amp;" in rendered
    assert "<span" not in rendered

    rendered_match = _SegmentCard._render_highlighted_html("A &amp_word & B", "amp")
    assert "&amp;" in rendered_match
    assert "<span" in rendered_match


def test_audio_odd_bytes_multichannel_and_monitor_mic_classification() -> None:
    # 6-channel (5.1) audio + trailing odd byte must not raise ValueError
    pcm_6ch = (np.zeros(6 * 480, dtype=np.int16)).tobytes() + b"\x00"
    out = resample_to_16k_mono(pcm_6ch, 6, 48000)
    assert out.ndim == 1 and out.size > 0

    # Physical monitor microphone must not be misclassified as a Linux loopback sink
    assert is_virtual_loopback_name("LG UltraFine Monitor Mic", "linux") is False
    assert is_virtual_loopback_name("alsa_output.pci.analog-stereo.monitor", "linux") is True
    assert is_virtual_loopback_name("Monitor of Built-in Audio", "linux") is True
    assert AppSettings().air_gapped_mode is False
