"""SQLite + FTS5 persistence for meetings, transcripts, and summaries."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from localminutes.models import Meeting, SummaryResult, TranscriptSegment


class MeetingDatabase:
    """Thread-safe SQLite database with FTS5 full-text search."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meetings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    duration_sec REAL NOT NULL DEFAULT 0.0,
                    language TEXT NOT NULL DEFAULT 'tr',
                    summary_json TEXT
                );

                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id INTEGER NOT NULL,
                    speaker TEXT NOT NULL,
                    text TEXT NOT NULL,
                    start_sec REAL NOT NULL DEFAULT 0.0,
                    end_sec REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_segments_meeting_id
                    ON segments(meeting_id, start_sec);

                CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
                    text,
                    speaker,
                    meeting_id UNINDEXED,
                    segment_id UNINDEXED,
                    tokenize='unicode61'
                );
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_meeting(
        self,
        title: Optional[str] = None,
        language: str = "tr",
        created_at: Optional[str] = None,
    ) -> Meeting:
        now = created_at or datetime.now().isoformat(timespec="seconds")
        final_title = title or f"Toplantı — {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO meetings (title, created_at, duration_sec, language) VALUES (?, ?, 0.0, ?)",
                (final_title, now, language),
            )
            meeting_id = int(cur.lastrowid)
        return Meeting(
            id=meeting_id,
            title=final_title,
            created_at=now,
            duration_sec=0.0,
            language=language,
        )

    def update_meeting(
        self,
        meeting_id: int,
        title: Optional[str] = None,
        duration_sec: Optional[float] = None,
    ) -> None:
        fields: list[str] = []
        values: list[object] = []
        if title is not None:
            fields.append("title = ?")
            values.append(title)
        if duration_sec is not None:
            fields.append("duration_sec = ?")
            values.append(duration_sec)
        if not fields:
            return
        values.append(meeting_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE meetings SET {', '.join(fields)} WHERE id = ?",
                values,
            )

    def save_summary(self, meeting_id: int, summary: SummaryResult) -> None:
        payload = json.dumps(
            {
                "overview": summary.overview,
                "key_points": summary.key_points,
                "decisions": summary.decisions,
                "action_items": summary.action_items,
                "raw_markdown": summary.raw_markdown,
                "model_used": summary.model_used,
                "generated_at": summary.generated_at,
            },
            ensure_ascii=False,
        )
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE meetings SET summary_json = ? WHERE id = ?",
                (payload, meeting_id),
            )

    def add_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        if segment.meeting_id is None:
            raise ValueError("TranscriptSegment.meeting_id must be set before saving.")
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO segments (meeting_id, speaker, text, start_sec, end_sec, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    segment.meeting_id,
                    segment.speaker,
                    segment.text,
                    segment.start_sec,
                    segment.end_sec,
                    segment.created_at,
                ),
            )
            seg_id = int(cur.lastrowid)
            self._conn.execute(
                "INSERT INTO segments_fts (text, speaker, meeting_id, segment_id) VALUES (?, ?, ?, ?)",
                (segment.text, segment.speaker, segment.meeting_id, seg_id),
            )
        segment.id = seg_id
        return segment

    def get_meeting(self, meeting_id: int, include_segments: bool = True) -> Optional[Meeting]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM meetings WHERE id = ?",
                (meeting_id,),
            ).fetchone()
            if row is None:
                return None
            meeting = self._row_to_meeting(row)
            if include_segments:
                seg_rows = self._conn.execute(
                    "SELECT * FROM segments WHERE meeting_id = ? ORDER BY start_sec ASC, id ASC",
                    (meeting_id,),
                ).fetchall()
                meeting.segments = [self._row_to_segment(r) for r in seg_rows]
            return meeting

    def list_meetings(self, limit: int = 200) -> list[Meeting]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM meetings ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_meeting(r) for r in rows]

    def delete_meeting(self, meeting_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM segments_fts WHERE meeting_id = ?", (meeting_id,))
            self._conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))

    def search_meetings(self, query: str, limit: int = 100) -> list[Meeting]:
        """Search meetings by title, summary, or FTS5 transcript content."""
        cleaned = query.strip()
        if not cleaned:
            return self.list_meetings(limit=limit)

        # Build safe FTS5 prefix query tokens
        tokens = [t.replace('"', "") for t in cleaned.split() if t.strip()]
        fts_query = " AND ".join(f'"{t}"*' for t in tokens) if tokens else ""
        like_pattern = f"%{cleaned}%"

        with self._lock:
            matched_ids: set[int] = set()

            # 1. Title or summary substring match
            rows = self._conn.execute(
                "SELECT id FROM meetings WHERE title LIKE ? OR COALESCE(summary_json, '') LIKE ?",
                (like_pattern, like_pattern),
            ).fetchall()
            matched_ids.update(int(r["id"]) for r in rows)

            # 2. FTS5 segment content match
            if fts_query:
                try:
                    fts_rows = self._conn.execute(
                        "SELECT DISTINCT meeting_id FROM segments_fts WHERE segments_fts MATCH ?",
                        (fts_query,),
                    ).fetchall()
                    matched_ids.update(int(r["meeting_id"]) for r in fts_rows)
                except sqlite3.OperationalError:
                    # Fallback to LIKE if FTS syntax is unusual
                    seg_rows = self._conn.execute(
                        "SELECT DISTINCT meeting_id FROM segments WHERE text LIKE ?",
                        (like_pattern,),
                    ).fetchall()
                    matched_ids.update(int(r["meeting_id"]) for r in seg_rows)

            if not matched_ids:
                return []

            placeholders = ",".join("?" for _ in matched_ids)
            meetings_rows = self._conn.execute(
                f"SELECT * FROM meetings WHERE id IN ({placeholders}) ORDER BY created_at DESC, id DESC LIMIT ?",
                (*matched_ids, limit),
            ).fetchall()
            return [self._row_to_meeting(r) for r in meetings_rows]

    @staticmethod
    def _row_to_meeting(row: sqlite3.Row) -> Meeting:
        summary: Optional[SummaryResult] = None
        if row["summary_json"]:
            try:
                data = json.loads(row["summary_json"])
                summary = SummaryResult(
                    overview=data.get("overview", ""),
                    key_points=list(data.get("key_points", [])),
                    decisions=list(data.get("decisions", [])),
                    action_items=list(data.get("action_items", [])),
                    raw_markdown=data.get("raw_markdown", ""),
                    model_used=data.get("model_used", ""),
                    generated_at=data.get("generated_at", ""),
                )
            except Exception:
                summary = None
        return Meeting(
            id=int(row["id"]),
            title=str(row["title"]),
            created_at=str(row["created_at"]),
            duration_sec=float(row["duration_sec"]),
            language=str(row["language"]),
            summary=summary,
        )

    @staticmethod
    def _row_to_segment(row: sqlite3.Row) -> TranscriptSegment:
        return TranscriptSegment(
            id=int(row["id"]),
            meeting_id=int(row["meeting_id"]),
            speaker=str(row["speaker"]),
            text=str(row["text"]),
            start_sec=float(row["start_sec"]),
            end_sec=float(row["end_sec"]),
            created_at=str(row["created_at"]),
        )
