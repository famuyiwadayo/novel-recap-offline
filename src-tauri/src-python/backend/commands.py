"""
All @commands.command() handlers — the IPC surface the frontend calls via
pyInvoke(). Thin by design: every command just translates frontend input
into a call against manager/network_mgr (from app.py) and returns a schema
(from schemas.py). No business logic lives here — that's task_queue.py,
network_manager.py, and the scraper plugins.
"""

from typing import List, Optional
from pytauri import Commands, AppHandle, Emitter

from backend.app import manager, network_mgr, db_manager

from backend.plugins import ImageDownloadPayload
from backend.scrapers.task_plugins import NovelDiscoveryPayload
from backend.schemas import (
    StatsPayload,
    TaskPayload,
    NovelPayload,
    ScrapeNovelArg,
    NovelIdArg,
    ChapterPayload,
    ResumeJobPayload,
    ResumeTaskPayload,
    PauseJobPayload,
    PauseTaskPayload,
    QueuePausedPayload,
    RetryTaskPayload,
    ConnectivityPayload,
    RetryFailedPayload,
    CancelJobPayload,
    CancelTaskPayload,
    GetJobStatsPayload,
    GetJobTasksPayload,
    task_payload,
    stats_payload,
    novel_payload,
    chapter_payload,
)

commands = Commands()


@commands.command()
async def scrape_novel(body: ScrapeNovelArg) -> int:
    """Start scraping a novel. novel_id is no longer supplied by the
    caller — the DB owns id generation now. Calling this again with the
    same source_url reuses the existing novel row (get_or_create_novel is
    idempotent) rather than creating a duplicate library entry, so it's
    safe to call as a "add or resume" action. Returns the novel_id — use
    group=str(novel_id) to filter 'task-update'/'queue-stats' events and
    to call retry_failed(group=str(novel_id)) later."""
    novel = await db_manager.get_or_create_novel(body.source_url)
    await manager.enqueue(
        "novel_discovery",
        NovelDiscoveryPayload(novel_id=novel.id, source_url=body.source_url),
        group=str(novel.id),
        priority=-10,  # discovery should jump ahead of any queued chapter/image work
    )
    return novel.id


@commands.command()
async def list_novels() -> List[NovelPayload]:
    """Everything in the library — the data source for a grid/list view.
    Persisted (SQLite), unlike task-queue state which resets on restart."""
    return [novel_payload(n) for n in await db_manager.list_novels()]


@commands.command()
async def get_novel(body: NovelIdArg) -> Optional[NovelPayload]:
    novel = await db_manager.get_novel(body.novel_id)
    return novel_payload(novel) if novel else None


@commands.command()
async def get_novel_chapters(body: NovelIdArg) -> List[ChapterPayload]:
    """Persisted chapter records (metadata + where each one lives on
    disk) — for a novel detail/reader view. Not the same as
    get_job_tasks(group), which shows the CURRENT in-progress queue state
    for that novel, including chapters not yet downloaded."""
    return [chapter_payload(c) for c in await db_manager.get_chapters(body.novel_id)]


@commands.command()
async def delete_novel(body: NovelIdArg) -> None:
    """Removes the novel and its chapter records from the library.
    Does NOT cancel an in-progress scrape for it — call cancel_job(group)
    first if one might be running, or this just deletes the DB record out
    from under an active job."""
    await db_manager.delete_novel(body.novel_id)


@commands.command()
async def download_image(body: ImageDownloadPayload) -> str:
    """Generic image download — usable outside the novel-scraping flow too
    (e.g. downloading a cover separately, or any other asset)."""
    task = await manager.enqueue(
        "image_download",
        body,
        priority=body.priority,
    )
    return task.id


@commands.command()
async def retry_failed(body: RetryFailedPayload) -> List[str]:
    """Retry every DEAD (retries-exhausted) task, optionally scoped to one
    novel/job (group). Returns the task ids requeued."""
    return await manager.requeue_failed(body.group)


@commands.command()
async def retry_task(body: RetryTaskPayload) -> bool:
    """Retry a single task right now, bypassing backoff."""
    return await manager.requeue(body.task_id)


@commands.command()
async def cancel_task(body: CancelTaskPayload) -> None:
    manager.cancel(body.task_id)


@commands.command()
async def cancel_job(body: CancelJobPayload) -> None:
    manager.cancel_group(body.group)


@commands.command()
async def pause_queue(app_handle: AppHandle) -> None:
    """Global pause — stops ALL workers from pulling new tasks, across
    every novel/job. For pausing just one novel or one chapter, use
    pause_job/pause_task below instead."""
    manager.pause()
    Emitter.emit(app_handle, "queue-paused", QueuePausedPayload(paused=True))


@commands.command()
async def resume_queue(app_handle: AppHandle) -> None:
    manager.resume()
    Emitter.emit(app_handle, "queue-paused", QueuePausedPayload(paused=False))


@commands.command()
async def get_queue_paused() -> QueuePausedPayload:
    """Current global-pause state — call once on app/component mount,
    since 'queue-paused' events only fire on CHANGES, not on demand.
    Doesn't reflect per-job/per-task pauses (pause_job/pause_task), only
    the global pause_queue()/resume_queue() toggle."""
    return QueuePausedPayload(paused=manager.is_paused)


@commands.command()
async def pause_task(body: PauseTaskPayload) -> None:
    """Hold one task out of the queue. If it's currently running, the
    default (cancel_running=False) lets it finish naturally and only holds
    its *next* attempt (e.g. a queued retry); pass cancel_running=True to
    stop it immediately instead."""
    manager.pause_task(body.task_id, cancel_running=body.cancel_running)


@commands.command()
async def resume_task(body: ResumeTaskPayload) -> bool:
    return await manager.resume_task(body.task_id)


@commands.command()
async def pause_job(body: PauseJobPayload) -> None:
    """Pause every task belonging to one novel/job, leaving other jobs
    running unaffected."""
    manager.pause_group(body.group, cancel_running=body.cancel_running)


@commands.command()
async def resume_job(body: ResumeJobPayload) -> List[str]:
    """Resume every held task in a job. Returns the task ids resumed."""
    return await manager.resume_group(body.group)


@commands.command()
async def get_job_stats(body: GetJobStatsPayload) -> StatsPayload:
    return stats_payload(manager.stats(body.group))


@commands.command()
async def get_job_tasks(body: GetJobTasksPayload) -> List[TaskPayload]:
    return [task_payload(t) for t in manager.tasks_in_group(body.group)]


@commands.command()
async def get_connectivity() -> ConnectivityPayload:
    return ConnectivityPayload(online=network_mgr.is_online)


# Frontend (TypeScript) sketch:
#
#   import { pyInvoke } from "tauri-plugin-pytauri-api";
#   import { listen } from "@tauri-apps/api/event";
#
#   type TaskUpdate = {
#     id: string; kind: string; group: string | null; priority: number;
#     state: "QUEUED"|"RUNNING"|"RETRYING"|"PAUSED"|"SUCCESS"|"DEAD"|"CANCELLED";
#     progress: number; message: string; error: string | null;
#     retries: number; result: unknown;
#   };
#   type Stats = {
#     group: string | null; total: number; queued: number; running: number;
#     retrying: number; paused: number; success: number; dead: number; cancelled: number;
#   };
#   type Connectivity = { online: boolean };
#
#   await listen<TaskUpdate>("task-update", (e) => {
#     // update a Map<taskId, TaskUpdate> keyed by e.payload.id, filtered by group in the UI
#   });
#   await listen<Stats>("queue-stats", (e) => setJobStats(e.payload.group, e.payload));
#   await listen<Connectivity>("connectivity", (e) => setOfflineBanner(!e.payload.online));
#   // pause/resume/requeue on connectivity change happens automatically on
#   // the backend — the frontend just needs this event to show a banner
#
#   await pyInvoke("scrape_novel", { novelId: 42, sourceUrl: url });
#   // ... later, if stats.dead > 0 (e.g. from a permanent NoScraperFound, not a network blip):
#   await pyInvoke("retry_failed", { group: String(novelId) });
#
#   // pause just one slow/flaky novel, leaving others downloading:
#   await pyInvoke("pause_job", { group: String(novelId) });
#   await pyInvoke("resume_job", { group: String(novelId) });
#
#   // pause a single chapter (e.g. user clicked a pause icon on one row):
#   await pyInvoke("pause_task", { taskId });
#   await pyInvoke("resume_task", { taskId });
#
#   // standalone image download, e.g. for a cover art grid, unrelated to any novel job:
#   await pyInvoke("download_image", { url: coverUrl, destPath: "covers/123.jpg" });
