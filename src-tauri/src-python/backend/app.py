import os
import sys
import asyncio

from pathlib import Path
from anyio.from_thread import start_blocking_portal
from pydantic import BaseModel
from collections.abc import Callable

from pytauri.path import PathResolver
from pytauri import (
    Commands,
    AppHandle,
    Emitter,
    # RunEvent,
    Manager,
    RunEventType,
    builder_factory,
    context_factory,
)
from pytauri_utils.async_tools import AsyncTools

from backend.plugins import ImageDownloadPlugin, ImageDownloadPayload
from backend.managers.task_queue import Task, TaskQueueManager, GroupStats
from backend.scrapers.task_plugins import (
    RegistryNovelDiscoveryPlugin,
    RegistryChapterFetchPlugin,
    NovelDiscoveryPayload,
)
from backend.managers.playwright_manager import PlaywrightManager
from backend.scrapers.base import NovelMetadata

# Your actual scraper registry (backend/scrapers/registry.py — dynamically
# loads instantiated scrapers from backend/scrapers/vendors/).
from backend.scrapers.registry import ScraperRegistry  # noqa: adjust import path to match your project

# NetworkManager now wraps PlaywrightManager directly (replaces
# headless_client.py) and adds offline-first connectivity awareness.
from backend.managers.network_manager import NetworkManager  # noqa: adjust import path


commands: Commands = Commands()

# One long-lived manager + one long-lived browser + one network_mgr for the
# whole app. Started lazily on first use (see _ensure_started) since
# pytauri's exact app-setup-hook shape may differ by version.
manager = TaskQueueManager(num_workers=5)
pw_manager = PlaywrightManager(headless=True, max_contexts=3)
network_mgr = NetworkManager(pw_manager)
scraper_registry = ScraperRegistry()

manager.register_plugin(RegistryNovelDiscoveryPlugin(scraper_registry, network_mgr))
manager.register_plugin(RegistryChapterFetchPlugin(scraper_registry, network_mgr))
manager.register_plugin(ImageDownloadPlugin())

app_handle: AppHandle
_started = False
_wired = False
