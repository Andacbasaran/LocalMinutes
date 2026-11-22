"""Unit tests for MeetingDatabase (SQLite + FTS5 + bookmarks/notes/edits)."""

from pathlib import Path

from localminutes.models import SummaryResult, TranscriptSegment
from localminutes.storage.database import MeetingDatabase


def test_crud_and_fts_search(tmp_path: Path) -> None:
    db = MeetingDatabase(tmp_path / "test.db")
    try:
        m1 = db.create_meeting(title="Haftalık Sprint Planlama", language="tr", template="technical")
        assert m1.id is not None

        s1 = db.add_segment(
            TranscriptSegment(
                meeting_id=m1.id,
                speaker="Sen",
                text="Veritabanı göçünü yarın sabaha kadar tamamlayalım.",
                start_sec=1.5,
                end_sec=4.2,
            )
        )
        s2 = db.add_segment(
            TranscriptSegment(
                meeting_id=m1.id,
                speaker="Karşı Taraf",
                text="Harika, ben de PyQt6 arayüz testlerini bitiriyorum.",
                start_sec=5.0,
                end_sec=8.5,
            )
        )
        assert s1.id is not None and s2.id is not None

        # Bookmark & edit segment (verifies FTS5 re-indexing)
        db.update_segment(s1.id, is_bookmarked=True, text="PostgreSQL göçünü yarın tamamlayalım.")
        db.update_meeting(m1.id, duration_sec=125.0, notes="Önemli not: canlıya Cuma çıkılacak.")

        summary = SummaryResult(
            overview="Sprint hedefleri ve teslim tarihleri netleştirildi.",
            key_points=["PostgreSQL göçü", "PyQt6 testleri"],
            decisions=["Yarın sabah entegrasyon yapılacak"],
            action_items=["Sen: PostgreSQL göçünü tamamla"],
            template="technical",
            model_used="ollama/qwen2.5:7b",
        )
        db.save_summary(m1.id, summary)

        loaded = db.get_meeting(m1.id)
        assert loaded is not None
        assert loaded.title == "Haftalık Sprint Planlama"
        assert loaded.template == "technical"
        assert loaded.duration_sec == 125.0
        assert "Cuma" in loaded.notes
        assert len(loaded.segments) == 2
        assert loaded.segments[0].is_bookmarked is True
        assert "PostgreSQL" in loaded.segments[0].text
        assert loaded.summary is not None
        assert loaded.summary.decisions == ["Yarın sabah entegrasyon yapılacak"]

        # FTS5 search matches edited text & notes
        assert len(db.search_meetings("PostgreSQL")) == 1
        assert len(db.search_meetings("Cuma")) == 1
        assert len(db.search_meetings("olmayan_kelime_xyz")) == 0

        # Delete single segment
        db.delete_segment(s2.id)
        loaded_after = db.get_meeting(m1.id)
        assert loaded_after is not None and len(loaded_after.segments) == 1

        # Cascade delete meeting
        db.delete_meeting(m1.id)
        assert db.get_meeting(m1.id) is None
        assert db.search_meetings("PostgreSQL") == []
    finally:
        db.close()
