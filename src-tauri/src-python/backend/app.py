"""
Application assembly: constructs the long-lived singletons (task queue,
browser, network manager), wires plugins into the queue, and exposes the
startup/shutdown lifecycle functions main.py calls.

No @commands.command() functions live here — those are in commands.py,
which imports manager/network_mgr FROM this module. This module never
imports commands.py, so there's no circularity.
"""

import asyncio
from pytauri.path import PathResolver
from pytauri import AppHandle, Emitter, Manager

from backend.managers.task_queue import TaskQueueManager, TaskState, Task
from backend.managers.playwright_manager import PlaywrightManager
from backend.managers.network_manager import NetworkManager
from backend.managers.db_manager import DBManager

from backend.plugins import ImageDownloadPlugin
from backend.scrapers.task_plugins import (
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


def _on_task_persist(t: Task) -> None:
    """Bridges the ephemeral task queue into persistent SQLite: on
    SUCCESS, write the real result into the novels/chapters tables. This
    runs alongside (not instead of) the task-update event emission in
    wire_events() below — same task, two independent listeners."""
    if t.state != TaskState.SUCCESS or t.group is None:
        return
    novel_id = int(t.group)

    if t.kind == "novel_discovery":
        # t.result is the actual NovelMetadata object (not a dict) — see
        # RegistryNovelDiscoveryPlugin's PluginResult(data=metadata, ...)
        metadata = t.result
        _fire_and_forget(db_manager.update_novel_metadata(novel_id, metadata))

    elif t.kind == "chapter_fetch":
        # t.result here is deliberately just {"title": ..., "chars": ...}
        # (RegistryChapterFetchPlugin doesn't return full chapter content
        # into the queue) — chapter_number/url come from t.payload instead,
        # which IS available here since this listener runs in-process
        # Python, unlike the frontend's TaskPayload which omits it.
        payload = t.payload
        result = t.result if isinstance(t.result, dict) else {}
        _fire_and_forget(
            db_manager.upsert_chapter(
                novel_id=novel_id,
                chapter_number=payload.chapter_num,
                title=result.get("title"),
                source_url=payload.chapter_url,
            )
        )


def wire_events(app_handle: AppHandle) -> None:
    """Registers event-forwarding listeners. Plain sync function — no
    portal/async_tools needed, since registering a callback is not itself
    an async operation. Call once from __init__.py."""

    path_resolver: PathResolver = Manager.path(app_handle)
    app_data_dir = path_resolver.app_data_dir()

    db_path = app_data_dir / "data" / "library.db"

    print(f"APP_DATA_DIR = {app_data_dir}\n\t{db_path}")

    # Mutates the EXISTING db_manager instance in place — does NOT do
    # `global db_manager; db_manager = DBManager(...)`. commands.py already
    # did `from backend.app import db_manager` at import time, which
    # snapshots that binding; reassigning the name here would leave
    # commands.py holding a stale reference to the original, never-started
    # instance while this module's own startup() started a different one.
    # set_db_path() avoids that entirely by never creating a new object.
    db_manager.set_db_path(db_path)

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
