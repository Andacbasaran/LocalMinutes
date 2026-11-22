"""Unit tests for Markdown, TXT, SRT, and JSON exporters."""

import json
from pathlib import Path

from localminutes.export.exporter import (
    export_meeting,
    format_json,
    format_markdown,
    format_srt,
    format_txt,
)
from localminutes.models import Meeting, SummaryResult, TranscriptSegment


def _sample_meeting() -> Meeting:
    return Meeting(
        id=1,
        title="Algoritma Dersi",
        created_at="2026-11-22T10:00:00",
        duration_sec=95.0,
        language="tr",
        template="lecture",
        notes="Sınavda dinamik programlama çıkacak.",
        summary=SummaryResult(
            overview="Dinamik programlama temelleri anlatıldı.",
            key_points=["Memoization", "Tabulation"],
            decisions=["Örnek problem: Knapsack"],
            action_items=["Haftaya 3 pratik soru çöz"],
            template="lecture",
        ),
        segments=[
            TranscriptSegment(
                speaker="Sen",
                text="Merhaba, başlayalım.",
                start_sec=2.0,
                end_sec=4.5,
                is_bookmarked=True,
            ),
            TranscriptSegment(
                speaker="Karşı Taraf",
                text="Tamamdır, dinliyorum.",
                start_sec=65.2,
                end_sec=68.0,
            ),
        ],
    )


def test_format_markdown_txt_srt_json(tmp_path: Path) -> None:
    meeting = _sample_meeting()

    md = format_markdown(meeting)
    assert "# Algoritma Dersi" in md
    assert "## Ders Özeti" in md
    assert "## ⭐ İşaretlenen Anlar" in md
    assert "## Toplantı Notları" in md
    assert "- [ ] Haftaya 3 pratik soru çöz" in md
    assert "⭐ **[00:02] Sen:** Merhaba, başlayalım." in md

    txt = format_txt(meeting)
    assert "TRANSKRİPT" in txt
    assert "[*] [00:02] Sen: Merhaba, başlayalım." in txt
    assert "NOTLAR" in txt

    srt = format_srt(meeting)
    assert "00:00:02,000 --> 00:00:04,500" in srt
    assert "Sen: Merhaba, başlayalım." in srt

    raw_json = format_json(meeting)
    parsed = json.loads(raw_json)
    assert parsed["title"] == "Algoritma Dersi"
    assert len(parsed["segments"]) == 2
    assert parsed["segments"][0]["is_bookmarked"] is True

    for ext in ("md", "txt", "srt", "json"):
        out = export_meeting(meeting, tmp_path / f"out.{ext}", ext)
        assert out.exists()
