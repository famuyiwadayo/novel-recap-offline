"""
All @commands.command() handlers — the IPC surface the frontend calls via
pyInvoke(). Thin by design: every command just translates frontend input
into a call against manager/network_mgr (from app.py) and returns a schema
(from schemas.py). No business logic lives here — that's task_queue.py,
network_manager.py, and the scraper plugins.
"""

from typing import List, Optional

from pytauri import Commands

from backend.app import manager, network_mgr
from backend.plugins import ImageDownloadPayload
from backend.scrapers.task_plugins import NovelDiscoveryPayload
from backend.schemas import (
    StatsPayload,
    TaskPayload,
    ConnectivityPayload,
    task_payload,
    stats_payload,
)

commands = Commands()


@commands.command()
async def scrape_novel(novel_id: int, source_url: str) -> None:
    """Start scraping a novel. novel_id is supplied by the caller rather than
    generated here — it presumably already exists (e.g. a DB row you created
    before kicking off the scrape), matching ExtractedChapter.novel_id's
    type. Use group=str(novel_id) to filter 'task-update'/'queue-stats'
    events and to call retry_failed(group=str(novel_id)) later."""
    await manager.enqueue(
        "novel_discovery",
        NovelDiscoveryPayload(novel_id=novel_id, source_url=source_url),
        group=str(novel_id),
        priority=-10,  # discovery should jump ahead of any queued chapter/image work
    )


@commands.command()
async def download_image(url: str, dest_path: str, priority: int = 0) -> str:
    """Generic image download — usable outside the novel-scraping flow too
    (e.g. downloading a cover separately, or any other asset)."""
    task = await manager.enqueue(
        "image_download",
        ImageDownloadPayload(url=url, dest_path=dest_path),
        priority=priority,
    )
    return task.id


@commands.command()
async def retry_failed(group: Optional[str] = None) -> List[str]:
    """Retry every DEAD (retries-exhausted) task, optionally scoped to one
    novel/job (group). Returns the task ids requeued."""
    return await manager.requeue_failed(group)


@commands.command()
async def retry_task(task_id: str) -> bool:
    """Retry a single task right now, bypassing backoff."""
    return await manager.requeue(task_id)


@commands.command()
async def cancel_task(task_id: str) -> None:
    manager.cancel(task_id)


@commands.command()
async def cancel_job(group: str) -> None:
    manager.cancel_group(group)


@commands.command()
async def pause_queue() -> None:
    """Global pause — stops ALL workers from pulling new tasks, across
    every novel/job. For pausing just one novel or one chapter, use
    pause_job/pause_task below instead."""
    manager.pause()


@commands.command()
async def resume_queue() -> None:
    manager.resume()


@commands.command()
async def pause_task(task_id: str, cancel_running: bool = False) -> None:
    """Hold one task out of the queue. If it's currently running, the
    default (cancel_running=False) lets it finish naturally and only holds
    its *next* attempt (e.g. a queued retry); pass cancel_running=True to
    stop it immediately instead."""
    manager.pause_task(task_id, cancel_running=cancel_running)


@commands.command()
async def resume_task(task_id: str) -> bool:
    return await manager.resume_task(task_id)


@commands.command()
async def pause_job(group: str, cancel_running: bool = False) -> None:
    """Pause every task belonging to one novel/job, leaving other jobs
    running unaffected."""
    manager.pause_group(group, cancel_running=cancel_running)


@commands.command()
async def resume_job(group: str) -> List[str]:
    """Resume every held task in a job. Returns the task ids resumed."""
    return await manager.resume_group(group)


@commands.command()
async def get_job_stats(group: Optional[str] = None) -> StatsPayload:
    return stats_payload(manager.stats(group))


@commands.command()
async def get_job_tasks(group: str) -> List[TaskPayload]:
    return [task_payload(t) for t in manager.tasks_in_group(group)]


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
