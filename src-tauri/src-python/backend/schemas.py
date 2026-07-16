"""
Pydantic models for IPC — everything that crosses the Tauri boundary
(command return types, emitted events) lives here, plus the small mapping
functions that turn internal dataclasses (Task, GroupStats) into these.

No dependency on app.py or commands.py — both of those import FROM here,
never the other way around.
"""

from pydantic import BaseModel
from typing import Any, Optional, List

from backend.managers.task_queue import Task, GroupStats
from backend.managers.db_manager import NovelRecord, ChapterRecord


class TaskPayload(BaseModel):
    id: str
    kind: str
    group: Optional[str]
    priority: int
    state: str
    progress: float
    message: str
    error: Optional[str]
    retries: int
    result: Any


class StatsPayload(BaseModel):
    group: Optional[str]
    total: int
    queued: int
    running: int
    retrying: int
    paused: int
    success: int
    dead: int
    cancelled: int


class ConnectivityPayload(BaseModel):
    online: bool


class QueuePausedPayload(BaseModel):
    paused: bool


class ScrapeNovelArg(BaseModel):
    source_url: str


class NovelIdArg(BaseModel):
    novel_id: int


class DownloadImagePayload(BaseModel):
    url: str
    dest_path: str
    priority: int = 0


class RetryFailedPayload(BaseModel):
    group: Optional[str] = None


class RetryTaskPayload(BaseModel):
    task_id: str


class CancelTaskPayload(BaseModel):
    task_id: str


class CancelJobPayload(BaseModel):
    group: str


class PauseTaskPayload(BaseModel):
    task_id: str
    cancel_running: bool = False


class ResumeTaskPayload(BaseModel):
    task_id: str


class PauseJobPayload(BaseModel):
    group: str
    cancel_running: bool = False


class ResumeJobPayload(BaseModel):
    group: str


class GetJobStatsPayload(BaseModel):
    group: Optional[str] = None


class GetJobTasksPayload(BaseModel):
    group: str


class NovelPayload(BaseModel):
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


class ChapterPayload(BaseModel):
    novel_id: int
    chapter_number: int
    title: Optional[str]
    source_url: Optional[str]
    content_path: Optional[str]
    downloaded_at: Optional[str]


class GetChapterContentArg(BaseModel):
    novel_id: int
    chapter_number: int


def novel_payload(n: NovelRecord) -> NovelPayload:
    return NovelPayload(
        id=n.id,
        source_url=n.source_url,
        title=n.title,
        author=n.author,
        other_titles=n.other_titles,
        tags=n.tags,
        summary=n.summary,
        status=n.status,
        cover_image_url=n.cover_image_url,
        cover_image_path=n.cover_image_path,
        total_chapters=n.total_chapters,
        downloaded_chapters=n.downloaded_chapters,
        scrape_state=n.scrape_state,
        added_at=n.added_at,
        updated_at=n.updated_at,
    )


def chapter_payload(c: ChapterRecord) -> ChapterPayload:
    return ChapterPayload(
        novel_id=c.novel_id,
        chapter_number=c.chapter_number,
        title=c.title,
        source_url=c.source_url,
        content_path=c.content_path,
        downloaded_at=c.downloaded_at,
    )


def task_payload(t: Task) -> TaskPayload:
    return TaskPayload(
        id=t.id,
        kind=t.kind,
        group=t.group,
        priority=t.priority,
        state=t.state.name,
        progress=t.progress,
        message=t.message,
        error=t.error,
        retries=t.retries,
        result=t.result,
    )


def stats_payload(s: GroupStats) -> StatsPayload:
    return StatsPayload(
        group=s.group,
        total=s.total,
        queued=s.queued,
        running=s.running,
        retrying=s.retrying,
        paused=s.paused,
        success=s.success,
        dead=s.dead,
        cancelled=s.cancelled,
    )
