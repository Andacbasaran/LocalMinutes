"""Unit tests for Markdown, TXT, and SRT exporters."""

from pathlib import Path

from localminutes.export.exporter import export_meeting, format_markdown, format_srt, format_txt
from localminutes.models import Meeting, SummaryResult, TranscriptSegment


def _sample_meeting() -> Meeting:
    return Meeting(
        id=1,
        title="Ürün Değerlendirme",
        created_at="2026-11-22T10:00:00",
        duration_sec=95.0,
        language="tr",
        summary=SummaryResult(
            overview="MVP özellikleri onaylandı.",
            key_points=["Offline deşifre", "WASAPI loopback"],
            decisions=["PyQt6 kullanılacak"],
            action_items=["İlk prototipi hazırla"],
        ),
        segments=[
            TranscriptSegment(speaker="Sen", text="Merhaba, başlayalım.", start_sec=2.0, end_sec=4.5),
            TranscriptSegment(
                speaker="Karşı Taraf", text="Tamamdır, dinliyorum.", start_sec=65.2, end_sec=68.0
            ),
        ],
    )


def test_format_markdown_txt_srt(tmp_path: Path) -> None:
    meeting = _sample_meeting()

    md = format_markdown(meeting)
    assert "# Ürün Değerlendirme" in md
    assert "- [ ] İlk prototipi hazırla" in md
    assert "**[00:02] Sen:** Merhaba, başlayalım." in md

    txt = format_txt(meeting)
    assert "TRANSKRİPT" in txt
    assert "[01:05] Karşı Taraf: Tamamdır, dinliyorum." in txt

    srt = format_srt(meeting)
    assert "00:00:02,000 --> 00:00:04,500" in srt
    assert "Sen: Merhaba, başlayalım." in srt
    assert "00:01:05,200 --> 00:01:08,000" in srt

    out_md = export_meeting(meeting, tmp_path / "out.md", "md")
    out_txt = export_meeting(meeting, tmp_path / "out.txt", "txt")
    out_srt = export_meeting(meeting, tmp_path / "out.srt", "srt")
    assert out_md.exists() and out_txt.exists() and out_srt.exists()
