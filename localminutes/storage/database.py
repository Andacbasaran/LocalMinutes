"""SQLite + FTS5 persistence for meetings, transcripts, notes, bookmarks, and summaries."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from localminutes.models import Meeting, SummaryResult, TranscriptSegment


class MeetingDatabase:
    """Thread-safe SQLite database with FTS5 full-text search and safe schema migrations."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._init_schema()
        self._run_migrations()

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
                    template TEXT NOT NULL DEFAULT 'meeting',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    notes TEXT NOT NULL DEFAULT '',
                    summary_json TEXT
                );

                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id INTEGER NOT NULL,
                    speaker TEXT NOT NULL,
                    text TEXT NOT NULL,
                    start_sec REAL NOT NULL DEFAULT 0.0,
                    end_sec REAL NOT NULL DEFAULT 0.0,
                    is_bookmarked INTEGER NOT NULL DEFAULT 0,
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

    def _run_migrations(self) -> None:
        """Safely add v0.2 columns to databases created with v0.1."""
        with self._lock, self._conn:
            meeting_cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(meetings)").fetchall()
            }
            if "template" not in meeting_cols:
                self._conn.execute(
                    "ALTER TABLE meetings ADD COLUMN template TEXT NOT NULL DEFAULT 'meeting'"
                )
            if "tags_json" not in meeting_cols:
                self._conn.execute(
                    "ALTER TABLE meetings ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "notes" not in meeting_cols:
                self._conn.execute(
                    "ALTER TABLE meetings ADD COLUMN notes TEXT NOT NULL DEFAULT ''"
                )

            seg_cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(segments)").fetchall()
            }
            if "is_bookmarked" not in seg_cols:
                self._conn.execute(
                    "ALTER TABLE segments ADD COLUMN is_bookmarked INTEGER NOT NULL DEFAULT 0"
                )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_meeting(
        self,
        title: Optional[str] = None,
        language: str = "tr",
        template: str = "meeting",
        tags: Optional[list[str]] = None,
        created_at: Optional[str] = None,
    ) -> Meeting:
        now = created_at or datetime.now().isoformat(timespec="seconds")
        final_title = title or f"Toplantı — {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        tag_list = list(tags or [])
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO meetings (title, created_at, duration_sec, language, template, tags_json, notes)
                VALUES (?, ?, 0.0, ?, ?, ?, '')
                """,
                (final_title, now, language, template, json.dumps(tag_list, ensure_ascii=False)),
            )
            meeting_id = int(cur.lastrowid)
        return Meeting(
            id=meeting_id,
            title=final_title,
            created_at=now,
            duration_sec=0.0,
            language=language,
            template=template,
            tags=tag_list,
            notes="",
        )

    def update_meeting(
        self,
        meeting_id: int,
        title: Optional[str] = None,
        duration_sec: Optional[float] = None,
        template: Optional[str] = None,
        tags: Optional[list[str]] = None,
        notes: Optional[str] = None,
    ) -> None:
        fields: list[str] = []
        values: list[object] = []
        if title is not None:
            fields.append("title = ?")
            values.append(title)
        if duration_sec is not None:
            fields.append("duration_sec = ?")
            values.append(duration_sec)
        if template is not None:
            fields.append("template = ?")
            values.append(template)
        if tags is not None:
            fields.append("tags_json = ?")
            values.append(json.dumps(tags, ensure_ascii=False))
        if notes is not None:
            fields.append("notes = ?")
            values.append(notes)
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
                "template": summary.template,
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
                INSERT INTO segments (meeting_id, speaker, text, start_sec, end_sec, is_bookmarked, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    segment.meeting_id,
                    segment.speaker,
                    segment.text,
                    segment.start_sec,
                    segment.end_sec,
                    1 if segment.is_bookmarked else 0,
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

    def update_segment(
        self,
        segment_id: int,
        text: Optional[str] = None,
        speaker: Optional[str] = None,
        is_bookmarked: Optional[bool] = None,
    ) -> None:
        fields: list[str] = []
        values: list[object] = []
        if text is not None:
            fields.append("text = ?")
            values.append(text)
        if speaker is not None:
            fields.append("speaker = ?")
            values.append(speaker)
        if is_bookmarked is not None:
            fields.append("is_bookmarked = ?")
            values.append(1 if is_bookmarked else 0)
        if not fields:
            return
        values.append(segment_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE segments SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            if text is not None or speaker is not None:
                row = self._conn.execute(
                    "SELECT meeting_id, speaker, text FROM segments WHERE id = ?",
                    (segment_id,),
                ).fetchone()
                if row is not None:
                    self._conn.execute("DELETE FROM segments_fts WHERE segment_id = ?", (segment_id,))
                    self._conn.execute(
                        "INSERT INTO segments_fts (text, speaker, meeting_id, segment_id) VALUES (?, ?, ?, ?)",
                        (row["text"], row["speaker"], row["meeting_id"], segment_id),
                    )

    def delete_segment(self, segment_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM segments_fts WHERE segment_id = ?", (segment_id,))
            self._conn.execute("DELETE FROM segments WHERE id = ?", (segment_id,))

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
        """Search meetings by title, notes, tags, summary, or FTS5 transcript content."""
        cleaned = query.strip()
        if not cleaned:
            return self.list_meetings(limit=limit)

        tokens = [t.replace('"', "") for t in cleaned.split() if t.strip()]
        fts_query = " AND ".join(f'"{t}"*' for t in tokens) if tokens else ""
        like_pattern = f"%{cleaned}%"

        with self._lock:
            matched_ids: set[int] = set()

            rows = self._conn.execute(
                """
                SELECT id FROM meetings
                WHERE title LIKE ?
                   OR COALESCE(summary_json, '') LIKE ?
                   OR COALESCE(notes, '') LIKE ?
                   OR COALESCE(tags_json, '') LIKE ?
                """,
                (like_pattern, like_pattern, like_pattern, like_pattern),
            ).fetchall()
            matched_ids.update(int(r["id"]) for r in rows)

            if fts_query:
                try:
                    fts_rows = self._conn.execute(
                        "SELECT DISTINCT meeting_id FROM segments_fts WHERE segments_fts MATCH ?",
                        (fts_query,),
                    ).fetchall()
                    matched_ids.update(int(r["meeting_id"]) for r in fts_rows)
                except sqlite3.OperationalError:
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
                    template=data.get("template", "meeting"),
                    raw_markdown=data.get("raw_markdown", ""),
                    model_used=data.get("model_used", ""),
                    generated_at=data.get("generated_at", ""),
                )
            except Exception:
                summary = None
        try:
            tags = list(json.loads(row["tags_json"] or "[]"))
        except Exception:
            tags = []
        return Meeting(
            id=int(row["id"]),
            title=str(row["title"]),
            created_at=str(row["created_at"]),
            duration_sec=float(row["duration_sec"]),
            language=str(row["language"]),
            template=str(row["template"] or "meeting"),
            tags=tags,
            notes=str(row["notes"] or ""),
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
            is_bookmarked=bool(row["is_bookmarked"]),
            created_at=str(row["created_at"]),
        )
