"""
Application assembly: constructs the long-lived singletons (task queue,
browser, network manager), wires plugins into the queue, and exposes the
startup/shutdown lifecycle functions main.py calls.

No @commands.command() functions live here — those are in commands.py,
which imports manager/network_mgr FROM this module. This module never
imports commands.py, so there's no circularity.
"""

from pytauri import AppHandle, Emitter

from backend.managers.task_queue import TaskQueueManager
from backend.managers.playwright_manager import PlaywrightManager
from backend.managers.network_manager import NetworkManager
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

manager.register_plugin(RegistryNovelDiscoveryPlugin(scraper_registry, network_mgr))
manager.register_plugin(RegistryChapterFetchPlugin(scraper_registry, network_mgr))
manager.register_plugin(ImageDownloadPlugin())


def wire_events(app_handle: AppHandle) -> None:
    """Registers event-forwarding listeners. Plain sync function — no
    portal/async_tools needed, since registering a callback is not itself
    an async operation. Call once from main.py."""
    manager.on_task(lambda t: Emitter.emit(app_handle, "task-update", task_payload(t)))
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
    """The one-time async part of startup — launching the browser. Call
    via `portal.call(startup)` from main.py so it BLOCKS until the browser
    is actually ready, before the app starts accepting IPC calls.
    manager.start()/network_mgr.start_monitoring() are NOT called here —
    they run forever; main.py schedules those via portal.start_task_soon."""
    await pw_manager.start()


async def shutdown() -> None:
    """Call from the window-close handler (see shutdown_listener.py) so
    the browser and queue shut down cleanly rather than being orphaned."""
    network_mgr.stop_monitoring()
    await manager.stop()
    await pw_manager.stop()
