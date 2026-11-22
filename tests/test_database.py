"""Unit tests for MeetingDatabase (SQLite + FTS5)."""

from pathlib import Path

from localminutes.models import SummaryResult, TranscriptSegment
from localminutes.storage.database import MeetingDatabase


def test_crud_and_fts_search(tmp_path: Path) -> None:
    db = MeetingDatabase(tmp_path / "test.db")
    try:
        m1 = db.create_meeting(title="Haftalık Sprint Planlama", language="tr")
        assert m1.id is not None

        db.add_segment(
            TranscriptSegment(
                meeting_id=m1.id,
                speaker="Sen",
                text="Veritabanı göçünü yarın sabaha kadar tamamlayalım.",
                start_sec=1.5,
                end_sec=4.2,
            )
        )
        db.add_segment(
            TranscriptSegment(
                meeting_id=m1.id,
                speaker="Karşı Taraf",
                text="Harika, ben de PyQt6 arayüz testlerini bitiriyorum.",
                start_sec=5.0,
                end_sec=8.5,
            )
        )

        summary = SummaryResult(
            overview="Sprint hedefleri ve teslim tarihleri netleştirildi.",
            key_points=["Veritabanı göçü", "PyQt6 testleri"],
            decisions=["Yarın sabah entegrasyon yapılacak"],
            action_items=["Sen: Veritabanı göçünü tamamla"],
            model_used="ollama/qwen2.5:7b",
        )
        db.save_summary(m1.id, summary)
        db.update_meeting(m1.id, duration_sec=125.0)

        loaded = db.get_meeting(m1.id)
        assert loaded is not None
        assert loaded.title == "Haftalık Sprint Planlama"
        assert loaded.duration_sec == 125.0
        assert len(loaded.segments) == 2
        assert loaded.summary is not None
        assert loaded.summary.decisions == ["Yarın sabah entegrasyon yapılacak"]

        # FTS5 search by transcript content
        results = db.search_meetings("Veritabanı")
        assert len(results) == 1
        assert results[0].id == m1.id

        # Search by title
        assert len(db.search_meetings("Sprint")) == 1
        assert len(db.search_meetings("olmayan_kelime_xyz")) == 0

        # Cascade delete
        db.delete_meeting(m1.id)
        assert db.get_meeting(m1.id) is None
        assert db.search_meetings("Veritabanı") == []
    finally:
        db.close()
