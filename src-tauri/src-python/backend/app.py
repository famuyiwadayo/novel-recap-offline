"""
Application assembly: constructs the long-lived singletons (task queue,
browser, network manager), wires plugins into the queue, and exposes the
startup/shutdown lifecycle functions main.py calls.

No @commands.command() functions live here — those are in commands.py,
which imports manager/network_mgr FROM this module. This module never
imports commands.py, so there's no circularity.
"""

import asyncio
from typing import Any, Dict
from pytauri.path import PathResolver
from pytauri import AppHandle, Emitter, Manager

from backend.managers.task_queue import TaskQueueManager, TaskState, Task
from backend.managers.playwright_manager import PlaywrightManager
from backend.managers.network_manager import NetworkManager
from backend.managers.db_manager import DBManager
from backend.managers.app_paths import app_paths

from backend.plugins import (
    ImageDownloadPlugin,
    NovelCoverDownloadPlugin,
    ImageDownloadPayload,
)
from backend.scrapers.task_plugins import (
    NovelDiscoveryPayload,
    ChapterFetchPayload,
    RegistryNovelDiscoveryPlugin,
    RegistryChapterFetchPlugin,
)
from backend.scrapers.registry import ScraperRegistry  # noqa: adjust import path to match your project
from backend.schemas import ConnectivityPayload, task_payload, stats_payload

# One long-lived manager + one long-lived browser + one network_mgr for the
# whole app's lifetime.
manager = TaskQueueManager(num_workers=5)
pw_manager = PlaywrightManager(headless=True, max_contexts=3)
network_mgr = NetworkManager(pw_manager)
scraper_registry = ScraperRegistry()
db_manager = DBManager(
    db_path="data/novels.db"
)  # adjust to a real app-data dir before shipping

manager.register_plugin(RegistryNovelDiscoveryPlugin(scraper_registry, network_mgr))
manager.register_plugin(RegistryChapterFetchPlugin(scraper_registry, network_mgr))
manager.register_plugin(ImageDownloadPlugin())
manager.register_plugin(NovelCoverDownloadPlugin())


def _fire_and_forget(coro) -> None:
    """Schedule a background coroutine from a sync callback context
    without awaiting it. manager.on_task() callbacks are plain sync
    functions called from within _set_task — but a DB write is async
    (aiosqlite), so it has to be scheduled rather than awaited directly.
    Logs failures instead of letting them vanish silently, which
    fire-and-forget asyncio tasks otherwise do by default."""
    task = asyncio.create_task(coro)

    def _log_if_failed(t: "asyncio.Task") -> None:
        exc = t.exception()
        if exc is not None:
            print(f"[db_manager] background write failed: {exc!r}")

    task.add_done_callback(_log_if_failed)


async def _persist_discovery_success(novel_id: int, metadata: Any) -> None:
    await db_manager.update_novel_metadata(novel_id, metadata)
    # Seeds one placeholder row per chapter (source_url known, not yet
    # downloaded) — this is what makes get_missing_chapters()/reconcile_novel()
    # possible later, including after a crash wipes the in-memory task queue.
    await db_manager.seed_chapters(novel_id, metadata.chapter_urls)

    if metadata.cover_image_url:
        novel = await db_manager.get_novel(novel_id)
        if novel and not novel.cover_image_path:
            await manager.enqueue(
                "novel_cover_download",
                ImageDownloadPayload(
                    url=metadata.cover_image_url,
                    dest_path=str(app_paths.cover_path(novel_id)),
                ),
                group=str(novel_id),
            )


async def _persist_discovery_failure(novel_id: int) -> None:
    await db_manager.set_novel_scrape_state(novel_id, "error")


async def _persist_chapter_success(
    novel_id: int, payload: ChapterFetchPayload, result: Dict[str, Any]
) -> None:
    await db_manager.upsert_chapter(
        novel_id=novel_id,
        chapter_number=payload.chapter_num,
        title=result.get("title"),
        source_url=payload.chapter_url,
        content_path=result.get("content_path"),
    )


async def _persist_cover_success(novel_id: int, result: Dict[str, Any]) -> None:
    path = result.get("path")
    if path:
        await db_manager.set_novel_cover_path(novel_id, path)


def _on_task_persist(t: Task) -> None:
    """Bridges the ephemeral task queue into persistent SQLite. Runs
    alongside (not instead of) the task-update event emission in
    wire_events() below — same task, two independent listeners."""
    if t.group is None or not t.group.isdigit():
        return  # group isn't a novel id — nothing to persist against
    novel_id = int(t.group)

    if t.state == TaskState.SUCCESS:
        if t.kind == "novel_discovery":
            # t.result is the actual NovelMetadata object (not a dict) —
            # see RegistryNovelDiscoveryPlugin's PluginResult(data=metadata, ...)
            _fire_and_forget(_persist_discovery_success(novel_id, t.result))
        elif t.kind == "chapter_fetch":
            result = t.result if isinstance(t.result, dict) else {}
            _fire_and_forget(_persist_chapter_success(novel_id, t.payload, result))
        elif t.kind == "novel_cover_download":
            result = t.result if isinstance(t.result, dict) else {}
            _fire_and_forget(_persist_cover_success(novel_id, result))

    elif t.state == TaskState.DEAD:
        if t.kind == "novel_discovery":
            _fire_and_forget(_persist_discovery_failure(novel_id))
        # chapter_fetch/novel_cover_download DEAD: no novel-level state
        # change needed — it just stays short of 'complete'/no cover;
        # retry_failed()/resume_novel() are how the user brings it back.


async def reconcile_novel(novel_id: int, source_url: str, scrape_state: str) -> None:
    """Self-correcting: re-enqueues whatever's missing for this novel —
    whether never attempted, or lost to an app crash/force-quit/unhandled
    bug that left the in-memory task queue forgetting about it. Safe to
    call on an already-complete novel (no-op) or while a job for it is
    already running (skips anything with a live, non-terminal task)."""
    if scrape_state in ("pending", "discovering"):
        # discovery never finished — get_or_create_novel is idempotent,
        # so re-running this reuses the existing row rather than duplicating
        await db_manager.set_novel_scrape_state(novel_id, "discovering")
        await manager.enqueue(
            "novel_discovery",
            NovelDiscoveryPayload(novel_id=novel_id, source_url=source_url),
            group=str(novel_id),
            priority=-10,
        )
        return

    live = manager.tasks_in_group(str(novel_id))
    live_chapter_nums = {
        t.payload.chapter_num
        for t in live
        if t.kind == "chapter_fetch"
        and t.state not in (TaskState.DEAD, TaskState.CANCELLED, TaskState.SUCCESS)
    }
    missing = await db_manager.get_missing_chapters(novel_id)
    for ch in missing:
        if ch.chapter_number in live_chapter_nums:
            continue
        await manager.enqueue(
            "chapter_fetch",
            ChapterFetchPayload(
                novel_id=novel_id,
                chapter_url=ch.source_url if ch.source_url else "",
                chapter_num=ch.chapter_number,
            ),
            priority=ch.chapter_number,
            group=str(novel_id),
        )
    if missing:
        await db_manager.set_novel_scrape_state(novel_id, "downloading")

    # cover can be missing/failed independently of chapters
    novel = await db_manager.get_novel(novel_id)
    if novel and novel.cover_image_url and not novel.cover_image_path:
        cover_already_live = any(
            t.kind == "novel_cover_download"
            and t.state not in (TaskState.DEAD, TaskState.CANCELLED, TaskState.SUCCESS)
            for t in live
        )
        if not cover_already_live:
            await manager.enqueue(
                "novel_cover_download",
                ImageDownloadPayload(
                    url=novel.cover_image_url,
                    dest_path=str(app_paths.cover_path(novel_id)),
                ),
                group=str(novel_id),
            )


async def reconcile_all_novels() -> None:
    """Called once at app startup — brings back any novel whose
    discovery/download was left incomplete by a previous session ending
    abnormally. This is what makes an interrupted download self-correct
    on next launch instead of silently staying stuck forever."""
    stale = await db_manager.get_novels_needing_reconciliation()
    for n in stale:
        await reconcile_novel(n.id, n.source_url, n.scrape_state)


def wire_events(app_handle: AppHandle) -> None:
    """Registers event-forwarding listeners. Plain sync function — no
    portal/async_tools needed, since registering a callback is not itself
    an async operation. Call once from __init__.py."""

    path_resolver: PathResolver = Manager.path(app_handle)
    app_data_dir = path_resolver.app_data_dir()

    path_resolver: PathResolver = Manager.path(app_handle)
    app_data_dir = path_resolver.app_data_dir()
    print(f"APP_DATA_DIR = {app_data_dir}")

    # db_path = app_data_dir / "data" / "library.db"

    # Configures the SINGLE shared app_paths singleton (scraped chapters,
    # covers, and the DB itself all resolve relative to this) — mutates
    # the existing instance in place, same reasoning as db_manager.
    # set_db_path() below, and for the identical reason: task_plugins.py
    # already did `from backend.managers.app_paths import app_paths` at
    # import time, so reassigning the name here instead of mutating it
    # would leave that module holding a stale, unconfigured instance.
    app_paths.configure(app_data_dir)

    # Mutates the EXISTING db_manager instance in place — does NOT do
    # `global db_manager; db_manager = DBManager(...)`. commands.py already
    # did `from backend.app import db_manager` at import time, which
    # snapshots that binding; reassigning the name here would leave
    # commands.py holding a stale reference to the original, never-started
    # instance while this module's own startup() started a different one.
    # set_db_path() avoids that entirely by never creating a new object.
    db_manager.set_db_path(app_paths.db_path)

    manager.on_task(lambda t: Emitter.emit(app_handle, "task-update", task_payload(t)))
    manager.on_task(_on_task_persist)
    manager.on_stats(
        lambda s: Emitter.emit(app_handle, "queue-stats", stats_payload(s))
    )

    async def _on_connectivity_change(online: bool) -> None:
        Emitter.emit(app_handle, "connectivity", ConnectivityPayload(online=online))
        if online:
            # resume pulling new tasks, then bring back anything that
            # exhausted its retries purely because we were offline
            manager.resume()
            await manager.requeue_failed()
        else:
            # stop pulling NEW tasks immediately rather than letting them
            # fail into retry/backoff pointlessly while offline; anything
            # already RUNNING will still hit wait_until_online() inside
            # NetworkManager and pause there too
            manager.pause()

    network_mgr.on_connectivity_change(_on_connectivity_change)


async def startup() -> None:
    """The one-time async part of startup — launching the browser and
    opening the database. Call via `portal.call(startup)` from main.py so
    it BLOCKS until both are actually ready, before the app starts
    accepting IPC calls. manager.start()/network_mgr.start_monitoring()
    are NOT called here — they run forever; main.py schedules those via
    portal.start_task_soon.

    Must run AFTER wire_events() has called db_manager.set_db_path() —
    main.py's ordering (wire_events, then portal.call(startup)) already
    guarantees this."""
    await pw_manager.start()
    await db_manager.start()


async def shutdown() -> None:
    """Call from the window-close handler (see shutdown_listener.py) so
    the browser, queue, and database shut down cleanly rather than being
    orphaned."""
    network_mgr.stop_monitoring()
    await manager.stop()
    await pw_manager.stop()
    await db_manager.stop()
