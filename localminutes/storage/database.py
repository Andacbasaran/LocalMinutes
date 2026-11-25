"""SQLite + FTS5 persistence for meetings, transcripts, notes, bookmarks, tags, and action items."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from localminutes.models import ActionItem, Meeting, SummaryResult, TranscriptSegment

_FTS_TOKEN_RE = re.compile(r"[0-9A-Za-z_çğıöşüÇĞİÖŞÜ]+", re.UNICODE)
_SPECIAL_SYMBOL_RE = re.compile(r"[+#$@./\\:%_-]")

_NON_ASSIGNEE_LABELS = frozenset(
    {
        "note",
        "notes",
        "todo",
        "to-do",
        "to do",
        "step",
        "http",
        "https",
        "ftp",
        "mailto",
        "warning",
        "warn",
        "important",
        "info",
        "reminder",
        "action",
        "action item",
        "decision",
        "risk",
        "blocker",
        "deadline",
        "due",
        "update",
        "not",
        "uyarı",
        "önemli",
    }
)


def _escape_like(value: str) -> str:
    """Escape SQLite LIKE wildcards (\\, %, _) for queries using ESCAPE '\\'."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _word_count(text: str) -> int:
    return len((text or "").split())


def _extract_assignee(item_text: str) -> tuple[str, str]:
    """Extract optional 'Name: task description' prefix into `(assignee, clean_text)`."""
    cleaned = item_text.strip().lstrip("-•*☐☑[] ").strip()
    if ":" in cleaned:
        prefix, rest = cleaned.split(":", 1)
        # Reject URL schemes (http://, https://, file://, etc.)
        if rest.startswith("//"):
            return "", cleaned
        prefix_clean = prefix.strip()
        rest_clean = rest.strip()
        if not prefix_clean or not rest_clean:
            return "", cleaned
        # Reject pure digits or time expressions like "14:30"
        if prefix_clean.isdigit() or re.fullmatch(r"[\d\s.\-/+]+", prefix_clean):
            return "", cleaned
        low = prefix_clean.lower()
        first_word = low.split()[0]
        if low in _NON_ASSIGNEE_LABELS or first_word in (
            "note",
            "todo",
            "step",
            "http",
            "https",
            "warning",
        ):
            return "", cleaned
        if not any(ch.isalpha() for ch in prefix_clean):
            return "", cleaned
        if 1 <= len(prefix_clean) <= 28 and len(prefix_clean.split()) <= 3:
            return prefix_clean, rest_clean
    return "", cleaned


class MeetingDatabase:
    """Thread-safe SQLite database with FTS5 full-text search, action items, and safe migrations."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA busy_timeout = 5000;")
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._init_schema()
        self._run_migrations()
        self._tighten_permissions()

    def _tighten_permissions(self) -> None:
        if os.name != "posix":
            return
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.db_path) + suffix)
            if p.exists():
                try:
                    os.chmod(p, 0o600)
                except OSError:
                    pass

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meetings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    duration_sec REAL NOT NULL DEFAULT 0.0,
                    language TEXT NOT NULL DEFAULT 'auto',
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
                    word_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_segments_meeting_id
                    ON segments(meeting_id, start_sec);

                CREATE TABLE IF NOT EXISTS action_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    assignee TEXT NOT NULL DEFAULT '',
                    due_date TEXT NOT NULL DEFAULT '',
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_action_items_meeting
                    ON action_items(meeting_id, completed);

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
        """Safely migrate databases created with v0.1 / v0.2 to v1.0.0."""
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
            if "word_count" not in seg_cols:
                self._conn.execute(
                    "ALTER TABLE segments ADD COLUMN word_count INTEGER NOT NULL DEFAULT 0"
                )
                cur = self._conn.execute("SELECT id, text FROM segments")
                batch: list[tuple[int, int]] = []
                for row in cur:
                    batch.append((_word_count(str(row["text"])), int(row["id"])))
                    if len(batch) >= 500:
                        self._conn.executemany(
                            "UPDATE segments SET word_count = ? WHERE id = ?",
                            batch,
                        )
                        batch.clear()
                if batch:
                    self._conn.executemany(
                        "UPDATE segments SET word_count = ? WHERE id = ?",
                        batch,
                    )

            # Ensure action_items table exists on migrated DBs
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS action_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    assignee TEXT NOT NULL DEFAULT '',
                    due_date TEXT NOT NULL DEFAULT '',
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Meetings CRUD
    # ------------------------------------------------------------------

    def create_meeting(
        self,
        title: Optional[str] = None,
        language: str = "auto",
        template: str = "meeting",
        tags: Optional[list[str]] = None,
        created_at: Optional[str] = None,
        notes: str = "",
        duration_sec: float = 0.0,
    ) -> Meeting:
        now = created_at or datetime.now().isoformat(timespec="seconds")
        final_title = title or f"Meeting — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        tag_list = [t.strip() for t in (tags or []) if t.strip()]
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO meetings (title, created_at, duration_sec, language, template, tags_json, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    final_title,
                    now,
                    float(duration_sec),
                    language,
                    template,
                    json.dumps(tag_list, ensure_ascii=False),
                    notes,
                ),
            )
            meeting_id = int(cur.lastrowid)
        return Meeting(
            id=meeting_id,
            title=final_title,
            created_at=now,
            duration_sec=float(duration_sec),
            language=language,
            template=template,
            tags=tag_list,
            notes=notes,
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
            values.append(float(duration_sec))
        if template is not None:
            fields.append("template = ?")
            values.append(template)
        if tags is not None:
            clean_tags = [t.strip() for t in tags if t.strip()]
            fields.append("tags_json = ?")
            values.append(json.dumps(clean_tags, ensure_ascii=False))
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

    def save_summary(
        self,
        meeting_id: int,
        summary: SummaryResult,
        sync_action_items: bool = True,
    ) -> list[ActionItem]:
        """Persist summary JSON and optionally sync extracted action items into `action_items` table."""
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
            if sync_action_items and summary.action_items:
                existing_rows = self._conn.execute(
                    "SELECT text FROM action_items WHERE meeting_id = ?",
                    (meeting_id,),
                ).fetchall()
                existing_norm = {str(r["text"]).strip().lower() for r in existing_rows}
                now = datetime.now().isoformat(timespec="seconds")
                for raw_item in summary.action_items:
                    assignee, clean_text = _extract_assignee(raw_item)
                    if not clean_text or clean_text.lower() in existing_norm:
                        continue
                    self._conn.execute(
                        """
                        INSERT INTO action_items (meeting_id, text, assignee, due_date, completed, created_at)
                        VALUES (?, ?, ?, '', 0, ?)
                        """,
                        (meeting_id, clean_text, assignee, now),
                    )
                    existing_norm.add(clean_text.lower())
        return self.list_action_items(meeting_id=meeting_id)

    # ------------------------------------------------------------------
    # Segments CRUD & Bulk Speaker Rename
    # ------------------------------------------------------------------

    def add_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        if segment.meeting_id is None:
            raise ValueError("TranscriptSegment.meeting_id must be set before saving.")
        wc = _word_count(segment.text)
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO segments (meeting_id, speaker, text, start_sec, end_sec, is_bookmarked, word_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    segment.meeting_id,
                    segment.speaker,
                    segment.text,
                    segment.start_sec,
                    segment.end_sec,
                    1 if segment.is_bookmarked else 0,
                    wc,
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

    def add_segments_bulk(self, segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
        """Batch-insert segments inside a single transaction for fast imports & benchmarks."""
        if not segments:
            return []
        with self._lock, self._conn:
            for seg in segments:
                if seg.meeting_id is None:
                    raise ValueError("TranscriptSegment.meeting_id must be set before saving.")
                wc = _word_count(seg.text)
                cur = self._conn.execute(
                    """
                    INSERT INTO segments (meeting_id, speaker, text, start_sec, end_sec, is_bookmarked, word_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        seg.meeting_id,
                        seg.speaker,
                        seg.text,
                        seg.start_sec,
                        seg.end_sec,
                        1 if seg.is_bookmarked else 0,
                        wc,
                        seg.created_at,
                    ),
                )
                seg_id = int(cur.lastrowid)
                seg.id = seg_id
                self._conn.execute(
                    "INSERT INTO segments_fts (text, speaker, meeting_id, segment_id) VALUES (?, ?, ?, ?)",
                    (seg.text, seg.speaker, seg.meeting_id, seg_id),
                )
        return segments

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
            fields.append("word_count = ?")
            values.append(_word_count(text))
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

    def bulk_rename_speaker(self, meeting_id: int, old_speaker: str, new_speaker: str) -> int:
        """Rename every segment from `old_speaker` to `new_speaker` in a meeting and update FTS5."""
        clean_new = new_speaker.strip()
        if not clean_new or clean_new == old_speaker:
            return 0
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT id, text FROM segments WHERE meeting_id = ? AND speaker = ?",
                (meeting_id, old_speaker),
            ).fetchall()
            if not rows:
                return 0
            self._conn.execute(
                "UPDATE segments SET speaker = ? WHERE meeting_id = ? AND speaker = ?",
                (clean_new, meeting_id, old_speaker),
            )
            for row in rows:
                seg_id = int(row["id"])
                self._conn.execute("DELETE FROM segments_fts WHERE segment_id = ?", (seg_id,))
                self._conn.execute(
                    "INSERT INTO segments_fts (text, speaker, meeting_id, segment_id) VALUES (?, ?, ?, ?)",
                    (row["text"], clean_new, meeting_id, seg_id),
                )
            return len(rows)

    def delete_segment(self, segment_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM segments_fts WHERE segment_id = ?", (segment_id,))
            self._conn.execute("DELETE FROM segments WHERE id = ?", (segment_id,))

    def get_meeting_max_end_sec(self, meeting_id: int) -> float:
        """Return the highest `end_sec` (or meeting `duration_sec`) for seamless resumed timestamps."""
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(end_sec) AS max_end FROM segments WHERE meeting_id = ?",
                (meeting_id,),
            ).fetchone()
            seg_max = float(row["max_end"]) if (row and row["max_end"] is not None) else 0.0
            m_row = self._conn.execute(
                "SELECT duration_sec FROM meetings WHERE id = ?",
                (meeting_id,),
            ).fetchone()
            m_dur = float(m_row["duration_sec"]) if (m_row and m_row["duration_sec"] is not None) else 0.0
            return max(seg_max, m_dur, 0.0)

    # ------------------------------------------------------------------
    # Action Items CRUD
    # ------------------------------------------------------------------

    def add_action_item(
        self,
        meeting_id: int,
        text: str,
        assignee: str = "",
        due_date: str = "",
        completed: bool = False,
    ) -> ActionItem:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Action item text cannot be empty.")
        if not assignee:
            parsed_assignee, parsed_text = _extract_assignee(clean_text)
            assignee = parsed_assignee
            clean_text = parsed_text
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO action_items (meeting_id, text, assignee, due_date, completed, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (meeting_id, clean_text, assignee.strip(), due_date.strip(), 1 if completed else 0, now),
            )
            item_id = int(cur.lastrowid)
        return ActionItem(
            id=item_id,
            meeting_id=meeting_id,
            text=clean_text,
            assignee=assignee.strip(),
            due_date=due_date.strip(),
            completed=bool(completed),
            created_at=now,
        )

    def list_action_items(
        self,
        meeting_id: Optional[int] = None,
        completed: Optional[bool] = None,
    ) -> list[ActionItem]:
        clauses: list[str] = []
        params: list[object] = []
        if meeting_id is not None:
            clauses.append("a.meeting_id = ?")
            params.append(meeting_id)
        if completed is not None:
            clauses.append("a.completed = ?")
            params.append(1 if completed else 0)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT a.*, m.title AS meeting_title
            FROM action_items a
            JOIN meetings m ON m.id = a.meeting_id
            {where}
            ORDER BY a.completed ASC, a.id DESC
        """
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [self._row_to_action_item(r) for r in rows]

    def toggle_action_item(self, item_id: int, completed: bool) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE action_items SET completed = ? WHERE id = ?",
                (1 if completed else 0, item_id),
            )

    def delete_action_item(self, item_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM action_items WHERE id = ?", (item_id,))

    def count_open_action_items(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM action_items WHERE completed = 0"
            ).fetchone()
            return int(row["cnt"]) if row else 0

    # ------------------------------------------------------------------
    # Retrieval, Insights & Search
    # ------------------------------------------------------------------

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
                meeting.action_items = self.list_action_items(meeting_id=meeting_id)
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
            self._conn.execute("DELETE FROM action_items WHERE meeting_id = ?", (meeting_id,))
            self._conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))

    def get_archive_insights(self) -> dict[str, Any]:
        """Compute global KPIs across the entire local SQLite archive without loading text into RAM."""
        with self._lock:
            m_row = self._conn.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(duration_sec), 0.0) AS total_dur FROM meetings"
            ).fetchone()
            seg_row = self._conn.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(word_count), 0) AS total_words FROM segments"
            ).fetchone()
            total_segments = int(seg_row["cnt"]) if seg_row else 0
            total_words = int(seg_row["total_words"]) if seg_row else 0
            open_tasks = self.count_open_action_items()
            done_row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM action_items WHERE completed = 1"
            ).fetchone()
            total_bytes = 0
            for suffix in ("", "-wal", "-shm"):
                p = Path(str(self.db_path) + suffix)
                if p.exists():
                    try:
                        total_bytes += p.stat().st_size
                    except OSError:
                        pass
            db_size_mb = round(total_bytes / (1024.0 * 1024.0), 3)
            return {
                "total_meetings": int(m_row["cnt"]) if m_row else 0,
                "total_duration_sec": float(m_row["total_dur"]) if m_row else 0.0,
                "total_segments": total_segments,
                "total_words": total_words,
                "open_action_items": open_tasks,
                "completed_action_items": int(done_row["cnt"]) if done_row else 0,
                "db_size_mb": db_size_mb,
                "db_size_kb": round(total_bytes / 1024.0, 1),
            }

    def import_meeting_object(self, meeting: Meeting) -> Meeting:
        """Persist a full Meeting object (e.g. Demo Meeting or JSON backup import) into the DB."""
        created = self.create_meeting(
            title=meeting.title,
            language=meeting.language,
            template=meeting.template,
            tags=meeting.tags,
            created_at=meeting.created_at,
            notes=meeting.notes,
            duration_sec=meeting.duration_sec,
        )
        assert created.id is not None
        segs = [
            TranscriptSegment(
                meeting_id=created.id,
                speaker=s.speaker,
                text=s.text,
                start_sec=s.start_sec,
                end_sec=s.end_sec,
                is_bookmarked=s.is_bookmarked,
                created_at=s.created_at,
            )
            for s in meeting.segments
        ]
        self.add_segments_bulk(segs)

        if meeting.action_items:
            for ai in meeting.action_items:
                self.add_action_item(
                    meeting_id=created.id,
                    text=ai.text,
                    assignee=ai.assignee,
                    due_date=ai.due_date,
                    completed=ai.completed,
                )
        if meeting.summary is not None:
            self.save_summary(
                created.id,
                meeting.summary,
                sync_action_items=(not bool(meeting.action_items)),
            )

        loaded = self.get_meeting(created.id, include_segments=True)
        return loaded or created

    def search_meetings(self, query: str, limit: int = 100) -> list[Meeting]:
        """Search meetings by title, notes, tags, summary, or FTS5 transcript content (punctuation-safe)."""
        cleaned = query.strip()
        if not cleaned:
            return self.list_meetings(limit=limit)

        like_pattern = f"%{_escape_like(cleaned)}%"
        has_special_symbols = bool(_SPECIAL_SYMBOL_RE.search(cleaned))
        tokens = _FTS_TOKEN_RE.findall(cleaned)
        fts_query = " AND ".join(f'"{t}"*' for t in tokens) if tokens else ""

        with self._lock:
            matched_ids: set[int] = set()

            rows = self._conn.execute(
                """
                SELECT id FROM meetings
                WHERE title LIKE ? ESCAPE '\\'
                   OR COALESCE(summary_json, '') LIKE ? ESCAPE '\\'
                   OR COALESCE(notes, '') LIKE ? ESCAPE '\\'
                   OR COALESCE(tags_json, '') LIKE ? ESCAPE '\\'
                """,
                (like_pattern, like_pattern, like_pattern, like_pattern),
            ).fetchall()
            matched_ids.update(int(r["id"]) for r in rows)

            if has_special_symbols or not fts_query:
                seg_rows = self._conn.execute(
                    "SELECT DISTINCT meeting_id FROM segments WHERE text LIKE ? ESCAPE '\\' OR speaker LIKE ? ESCAPE '\\'",
                    (like_pattern, like_pattern),
                ).fetchall()
                matched_ids.update(int(r["meeting_id"]) for r in seg_rows)
            else:
                try:
                    fts_rows = self._conn.execute(
                        "SELECT DISTINCT meeting_id FROM segments_fts WHERE segments_fts MATCH ?",
                        (fts_query,),
                    ).fetchall()
                    matched_ids.update(int(r["meeting_id"]) for r in fts_rows)
                except sqlite3.OperationalError:
                    seg_rows = self._conn.execute(
                        "SELECT DISTINCT meeting_id FROM segments WHERE text LIKE ? ESCAPE '\\'",
                        (like_pattern,),
                    ).fetchall()
                    matched_ids.update(int(r["meeting_id"]) for r in seg_rows)

            if not matched_ids:
                return []

            id_list = list(matched_ids)
            meetings_rows: list[sqlite3.Row] = []
            chunk_size = 500
            for idx in range(0, len(id_list), chunk_size):
                chunk = id_list[idx : idx + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                meetings_rows.extend(
                    self._conn.execute(
                        f"SELECT * FROM meetings WHERE id IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )
            meetings_rows.sort(
                key=lambda r: (str(r["created_at"]), int(r["id"])),
                reverse=True,
            )
            return [self._row_to_meeting(r) for r in meetings_rows[:limit]]

    def search_segments_fts(self, query: str, meeting_id: Optional[int] = None, limit: int = 25) -> list[int]:
        """Fast FTS5 segment lookup returning matching segment IDs (used in benchmarks & search)."""
        cleaned = query.strip()
        if not cleaned:
            return []
        tokens = _FTS_TOKEN_RE.findall(cleaned)
        if not tokens:
            return []
        fts_query = " AND ".join(f'"{t}"*' for t in tokens)
        with self._lock:
            try:
                if meeting_id is not None:
                    rows = self._conn.execute(
                        "SELECT segment_id FROM segments_fts WHERE segments_fts MATCH ? AND meeting_id = ? LIMIT ?",
                        (fts_query, meeting_id, limit),
                    ).fetchall()
                else:
                    rows = self._conn.execute(
                        "SELECT segment_id FROM segments_fts WHERE segments_fts MATCH ? LIMIT ?",
                        (fts_query, limit),
                    ).fetchall()
                return [int(r["segment_id"]) for r in rows]
            except sqlite3.OperationalError:
                return []

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

    @staticmethod
    def _row_to_action_item(row: sqlite3.Row) -> ActionItem:
        return ActionItem(
            id=int(row["id"]),
            meeting_id=int(row["meeting_id"]),
            text=str(row["text"]),
            assignee=str(row["assignee"] or ""),
            due_date=str(row["due_date"] or ""),
            completed=bool(row["completed"]),
            meeting_title=str(row["meeting_title"]) if "meeting_title" in row.keys() else "",
            created_at=str(row["created_at"]),
        )
