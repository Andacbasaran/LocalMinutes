"""Unit tests for Action Items DB, offline BM25 Q&A, Air-Gapped mode, FTS5 edge cases, VTT/Obsidian & JSON import."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from localminutes.export.exporter import (
    build_demo_meeting,
    export_meeting,
    format_json,
    format_markdown,
    format_vtt,
    parse_meeting_json,
)
from localminutes.models import AppSettings, SummaryResult, TranscriptSegment
from localminutes.storage.database import MeetingDatabase
from localminutes.summarization.qa import ask_meeting, retrieve_bm25_citations
from localminutes.summarization.summarizer import (
    enhance_meeting_notes,
    list_ollama_models,
    summarize_meeting,
)


def test_action_items_persistence_toggle_and_summary_sync(tmp_path: Path) -> None:
    db = MeetingDatabase(tmp_path / "tasks.db")
    try:
        m = db.create_meeting(title="Release Readiness Review", template="technical")
        assert m.id is not None

        a1 = db.add_action_item(m.id, "Selin: Publish v1.0.0 release notes", due_date="Fri")
        a2 = db.add_action_item(m.id, "Verify Windows Inno Setup installer")
        assert a1.id is not None and a2.id is not None
        assert a1.assignee == "Selin"
        assert a1.text == "Publish v1.0.0 release notes"
        assert a2.assignee == ""
        assert db.count_open_action_items() == 2

        # Toggle completion & verify filters
        db.toggle_action_item(a1.id, True)
        assert db.count_open_action_items() == 1
        assert len(db.list_action_items(meeting_id=m.id, completed=True)) == 1
        assert len(db.list_action_items(meeting_id=m.id, completed=False)) == 1

        # save_summary deduplicates existing action items while adding new ones
        summary = SummaryResult(
            overview="Ready to ship v1.0.0.",
            decisions=["Ship Friday"],
            action_items=[
                "Selin: Publish v1.0.0 release notes",  # duplicate text -> skipped
                "Mert: Upload SHA256SUMS.txt",  # new -> added
            ],
            template="technical",
        )
        synced = db.save_summary(m.id, summary, sync_action_items=True)
        assert len(synced) == 3
        assert db.count_open_action_items() == 2

        insights = db.get_archive_insights()
        assert insights["total_meetings"] == 1
        assert insights["open_action_items"] == 2
        assert insights["completed_action_items"] == 1

        # Delete one item and verify cascade on meeting delete
        db.delete_action_item(a2.id)
        assert len(db.list_action_items(meeting_id=m.id)) == 2
        db.delete_meeting(m.id)
        assert db.list_action_items() == []
    finally:
        db.close()


def test_offline_bm25_qa_citations_and_turkish_prefix() -> None:
    segments = [
        TranscriptSegment(
            id=1,
            speaker="You",
            text="Let's finalize the PostgreSQL connection pooling latency target before Friday.",
            start_sec=10.0,
            end_sec=18.0,
            is_bookmarked=True,
        ),
        TranscriptSegment(
            id=2,
            speaker="Selin",
            text="macOS kullanıcıları için BlackHole 2ch kurulum rehberini dokümantasyona ekledim.",
            start_sec=22.0,
            end_sec=31.0,
        ),
        TranscriptSegment(
            id=3,
            speaker="Mert",
            text="Strict Air-Gapped Privacy Mode blocks every single outbound HTTP call.",
            start_sec=40.0,
            end_sec=49.0,
        ),
    ]

    cits_pg = retrieve_bm25_citations("What is the PostgreSQL latency target?", segments, top_k=3)
    assert len(cits_pg) >= 1
    assert cits_pg[0].segment_id == 1
    assert cits_pg[0].timestamp_sec == 10.0

    # Turkish agglutinative matching (dokümantasyon vs dokümantasyona)
    cits_tr = retrieve_bm25_citations("BlackHole kurulum dokümantasyon", segments, top_k=3)
    assert len(cits_tr) >= 1
    assert cits_tr[0].segment_id == 2

    settings = AppSettings(llm_provider="local_extractive")
    resp = ask_meeting("How does Air-Gapped Privacy Mode work?", segments, settings)
    assert resp.model_used == "local/bm25-offline"
    assert len(resp.citations) >= 1
    assert resp.citations[0].segment_id == 3
    assert "[00:40]" in resp.answer


def test_air_gapped_mode_strictly_blocks_all_outbound_http() -> None:
    segments = build_demo_meeting().segments
    settings = AppSettings(
        air_gapped_mode=True,
        llm_provider="openai_compatible",
        api_base_url="https://api.example.invalid/v1",
        api_key="sk-should-never-be-sent",
        ollama_url="http://127.0.0.1:11434",
    )

    def _forbid_http(*_args, **_kwargs):
        raise AssertionError("Air-gapped mode MUST NOT make any outbound HTTP request!")

    with patch("httpx.Client", side_effect=_forbid_http):
        assert list_ollama_models(settings.ollama_url, air_gapped_mode=True) == []

        summary = summarize_meeting(segments, settings, template="technical", notes="Ship Friday")
        assert summary.overview
        assert "Air-Gapped" in summary.model_used

        enhanced, model_used = enhance_meeting_notes(segments, "- Verify zero egress", settings)
        assert "Verify zero egress" in enhanced
        assert "Air-Gapped" in model_used

        qa = ask_meeting("When do we ship v1.0.0?", segments, settings)
        assert "Air-Gapped" in qa.model_used
        assert len(qa.citations) >= 1


def test_fts5_special_characters_turkish_and_bulk_speaker_rename(tmp_path: Path) -> None:
    db = MeetingDatabase(tmp_path / "fts_edge.db")
    try:
        m = db.create_meeting(title='Architecture "Zero-Bot" & C++ Review', tags=["c++", "türkçe"])
        assert m.id is not None
        db.add_segments_bulk(
            [
                TranscriptSegment(
                    meeting_id=m.id,
                    speaker="Remote",
                    text='We profiled the C++ CTranslate2 kernel and checked "quoted" tokens.',
                    start_sec=2.0,
                    end_sec=7.0,
                ),
                TranscriptSegment(
                    meeting_id=m.id,
                    speaker="Remote",
                    text="Türkçe şifre, ğüçöı karakterleri ve çığır açan hız doğrulandı.",
                    start_sec=8.0,
                    end_sec=14.0,
                ),
            ]
        )

        # Punctuation / FTS5 operator characters must never throw sqlite3.OperationalError
        for query in ('C++', '"quoted"', "Zero-Bot", "Türkçe şifre", "ğüçöı", "OR AND NOT ()*:", "c++"):
            res = db.search_meetings(query)
            if query != "OR AND NOT ()*:":
                assert len(res) == 1, f"Expected match for query: {query}"

        seg_hits = db.search_segments_fts("CTranslate2", meeting_id=m.id)
        assert len(seg_hits) == 1

        # Bulk rename updates segments AND FTS5 speaker index
        renamed_cnt = db.bulk_rename_speaker(m.id, "Remote", "Dr. Ayşe")
        assert renamed_cnt == 2
        loaded = db.get_meeting(m.id)
        assert loaded is not None
        assert all(s.speaker == "Dr. Ayşe" for s in loaded.segments)
        assert len(db.search_segments_fts("Ayşe", meeting_id=m.id)) == 2
    finally:
        db.close()


def test_vtt_obsidian_markdown_export_and_json_roundtrip(tmp_path: Path) -> None:
    demo = build_demo_meeting()

    # WebVTT export
    vtt = format_vtt(demo)
    assert vtt.startswith("WEBVTT\n")
    assert "00:00:04.000 --> 00:00:13.500" in vtt
    assert "<v You>" in vtt

    # Obsidian YAML frontmatter Markdown export with action item states
    obs_md = format_markdown(demo, obsidian_frontmatter=True)
    assert obs_md.startswith("---\n")
    assert 'title: "Q4 Product & Engineering Sprint — LocalMinutes v1.0 Launch"' in obs_md
    assert "source: LocalMinutes" in obs_md
    assert "  - v1.0-launch" in obs_md
    assert "- [x] **Selin (PM):**" in obs_md
    assert "- [ ] **Mert (Infra):**" in obs_md

    vtt_path = export_meeting(demo, tmp_path / "demo.vtt", "vtt")
    obs_path = export_meeting(demo, tmp_path / "demo_obs.md", "obsidian_md")
    assert vtt_path.exists() and "WEBVTT" in vtt_path.read_text(encoding="utf-8")
    assert obs_path.exists() and "source: LocalMinutes" in obs_path.read_text(encoding="utf-8")

    # Full JSON export -> parse -> DB import round-trip
    raw_json = format_json(demo)
    parsed = parse_meeting_json(raw_json)
    assert parsed.title == demo.title
    assert parsed.tags == demo.tags
    assert len(parsed.segments) == len(demo.segments)
    assert len(parsed.action_items) == len(demo.action_items)
    assert parsed.summary is not None and parsed.summary.decisions == demo.summary.decisions

    db = MeetingDatabase(tmp_path / "roundtrip.db")
    try:
        imported = db.import_meeting_object(parsed)
        assert imported.id is not None
        assert len(imported.segments) == len(demo.segments)
        assert len(imported.action_items) == len(demo.action_items)
        assert any(ai.completed for ai in imported.action_items)
    finally:
        db.close()

    with pytest.raises(ValueError):
        parse_meeting_json('{"not_a_meeting": true}')
