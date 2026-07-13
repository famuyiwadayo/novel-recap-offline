"""
backend/managers/db_manager.py

SQLite persistence for novels + chapters. Uses aiosqlite so DB calls stay
async-native — no anyio.to_thread wrapping needed, consistent with
everything else running on pytauri's asyncio backend.

Two deliberately different sources of truth:
  - TaskQueueManager (task_queue.py): EPHEMERAL, in-memory, "what's
    happening right now" — resets on every app restart.
  - DBManager (this file): PERSISTENT, "what's actually been achieved" —
    survives restarts, and is what a Library view renders from.

app.py's wire_events() bridges the two: when a novel_discovery or
chapter_fetch task reaches SUCCESS, a listener there writes the result
into SQLite. Chapter CONTENT stays on disk (see plugins.py's
persist_chapter) — this only tracks metadata + where each chapter lives,
keeping the DB small.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Union

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS novels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL UNIQUE,
    title TEXT,
    author TEXT,
    other_titles TEXT,
    tags TEXT,
    summary TEXT,
    status TEXT,
    cover_image_url TEXT,
    cover_image_path TEXT,
    total_chapters INTEGER NOT NULL DEFAULT 0,
    downloaded_chapters INTEGER NOT NULL DEFAULT 0,
    scrape_state TEXT NOT NULL DEFAULT 'pending',
    added_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapters (
    novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL,
    title TEXT,
    source_url TEXT,
    content_path TEXT,
    downloaded_at TEXT,
    PRIMARY KEY (novel_id, chapter_number)
);

CREATE INDEX IF NOT EXISTS idx_chapters_novel ON chapters(novel_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class NovelRecord:
    id: int
    source_url: str
    title: Optional[str]
    author: List[str]
    other_titles: List[str]
    tags: List[str]
    summary: Optional[str]
    status: Optional[str]
    cover_image_url: Optional[str]
    cover_image_path: Optional[str]
    total_chapters: int
    downloaded_chapters: int
    scrape_state: str
    added_at: str
    updated_at: str


@dataclass
class ChapterRecord:
    novel_id: int
    chapter_number: int
    title: Optional[str]
    source_url: Optional[str]
    content_path: Optional[str]
    downloaded_at: Optional[str]


def _row_to_novel(row: aiosqlite.Row) -> NovelRecord:
    return NovelRecord(
        id=row["id"],
        source_url=row["source_url"],
        title=row["title"],
        author=json.loads(row["author"]) if row["author"] else [],
        other_titles=json.loads(row["other_titles"]) if row["other_titles"] else [],
        tags=json.loads(row["tags"]) if row["tags"] else [],
        summary=row["summary"],
        status=row["status"],
        cover_image_url=row["cover_image_url"],
        cover_image_path=row["cover_image_path"],
        total_chapters=row["total_chapters"],
        downloaded_chapters=row["downloaded_chapters"],
        scrape_state=row["scrape_state"],
        added_at=row["added_at"],
        updated_at=row["updated_at"],
    )


def _row_to_chapter(row: aiosqlite.Row) -> ChapterRecord:
    return ChapterRecord(
        novel_id=row["novel_id"],
        chapter_number=row["chapter_number"],
        title=row["title"],
        source_url=row["source_url"],
        content_path=row["content_path"],
        downloaded_at=row["downloaded_at"],
    )


class DBManager:
    def __init__(self, db_path: Union[str, Path]) -> None:
        self._db_path = str(db_path)
        self._conn: Optional[aiosqlite.Connection] = None

    def set_db_path(self, db_path: Union[str, Path]) -> None:
        """Change where this instance will open its database, e.g. once
        you know the real OS-appropriate app-data directory (only
        available via AppHandle, which isn't known yet at module-import
        time when DBManager is first constructed).

        Deliberately mutates THIS instance rather than requiring callers
        to construct a new DBManager and reassign a global — anything
        that already did `from backend.app import db_manager` holds a
        snapshot of that name's binding at import time, and would NOT see
        a later `db_manager = DBManager(...)` reassignment in app.py (a
        classic from-import gotcha: rebinding a module-level name doesn't
        propagate to modules that already imported it). Mutating the
        existing object in place means every reference — however it was
        imported — still points at the same instance."""
        if self._conn is not None:
            raise RuntimeError(
                "Cannot change db_path after start() has already opened a connection"
            )
        self._db_path = str(db_path)

    async def start(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def stop(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "DBManager.start() not called yet"
        return self._conn

    # --- novels -----------------------------------------------------

    async def get_or_create_novel(self, source_url: str) -> NovelRecord:
        """Idempotent — re-scraping the same URL reuses the existing row
        instead of creating a duplicate. This is what makes scrape_novel()
        safe to call repeatedly for the same novel without piling up
        duplicate library entries."""
        existing = await self.get_novel_by_url(source_url)
        if existing is not None:
            return existing
        now = _now()
        cursor = await self.conn.execute(
            "INSERT INTO novels (source_url, scrape_state, added_at, updated_at) VALUES (?, 'pending', ?, ?)",
            (source_url, now, now),
        )
        await self.conn.commit()
        novel_id = cursor.lastrowid
        created = await self.get_novel(novel_id)  # type: ignore[arg-type]
        assert created is not None
        return created

    async def get_novel(self, novel_id: int) -> Optional[NovelRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM novels WHERE id = ?", (novel_id,)
        )
        row = await cursor.fetchone()
        return _row_to_novel(row) if row else None

    async def get_novel_by_url(self, source_url: str) -> Optional[NovelRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM novels WHERE source_url = ?", (source_url,)
        )
        row = await cursor.fetchone()
        return _row_to_novel(row) if row else None

    async def list_novels(self) -> List[NovelRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM novels ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [_row_to_novel(r) for r in rows]

    async def update_novel_metadata(self, novel_id: int, metadata: Any) -> None:
        """metadata is a NovelMetadata (scrapers/base.py) — call once
        novel_discovery succeeds."""
        await self.conn.execute(
            """UPDATE novels SET
                title = ?, author = ?, other_titles = ?, tags = ?, summary = ?,
                status = ?, cover_image_url = ?, total_chapters = ?,
                scrape_state = 'downloading', updated_at = ?
               WHERE id = ?""",
            (
                metadata.title,
                json.dumps(metadata.author),
                json.dumps(metadata.other_titles or []),
                json.dumps(metadata.tags or []),
                metadata.summary,
                metadata.status,
                metadata.cover_image_url,
                metadata.total_chapters,
                _now(),
                novel_id,
            ),
        )
        await self.conn.commit()

    async def set_novel_scrape_state(self, novel_id: int, state: str) -> None:
        """state: 'pending' | 'discovering' | 'downloading' | 'complete' | 'error'"""
        await self.conn.execute(
            "UPDATE novels SET scrape_state = ?, updated_at = ? WHERE id = ?",
            (state, _now(), novel_id),
        )
        await self.conn.commit()

    async def set_novel_cover_path(self, novel_id: int, path: str) -> None:
        await self.conn.execute(
            "UPDATE novels SET cover_image_path = ?, updated_at = ? WHERE id = ?",
            (path, _now(), novel_id),
        )
        await self.conn.commit()

    async def delete_novel(self, novel_id: int) -> None:
        await self.conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
        await self.conn.commit()

    # --- chapters -----------------------------------------------------

    async def upsert_chapter(
        self,
        novel_id: int,
        chapter_number: int,
        title: Optional[str],
        source_url: Optional[str],
    ) -> None:
        """Call once a chapter_fetch task succeeds. Recomputes
        downloaded_chapters on the parent novel from an actual COUNT
        rather than incrementing, so it self-corrects if a chapter is ever
        re-downloaded or the app restarts mid-job."""
        await self.conn.execute(
            """INSERT INTO chapters (novel_id, chapter_number, title, source_url, downloaded_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(novel_id, chapter_number) DO UPDATE SET
                 title = excluded.title, source_url = excluded.source_url,
                 downloaded_at = excluded.downloaded_at""",
            (novel_id, chapter_number, title, source_url, _now()),
        )
        await self.conn.execute(
            "UPDATE novels SET downloaded_chapters = "
            "(SELECT COUNT(*) FROM chapters WHERE novel_id = ?), updated_at = ? WHERE id = ?",
            (novel_id, _now(), novel_id),
        )
        await self.conn.commit()

    async def get_chapters(self, novel_id: int) -> List[ChapterRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM chapters WHERE novel_id = ? ORDER BY chapter_number",
            (novel_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_chapter(r) for r in rows]
