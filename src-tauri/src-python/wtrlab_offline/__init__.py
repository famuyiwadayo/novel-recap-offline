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


class Person(BaseModel):
    name: str


class ImportPayload(BaseModel):
    url: str


def get_resource_dir(app_handle_: AppHandle) -> Path:
    path_resolver: PathResolver = Manager.path(app_handle_)
    return path_resolver.resource_dir()


def resolve_browser_path(app_handle_: AppHandle) -> str:
    # 1. Check if we are running the final compiled production app
    # (PyEmbed sets sys.frozen or sets an immutable marker on standalone distributions)
    path_exists = os.path.exists("../src-tauri/binaries/ms-playwright")
    print(f"\n\nPATH EXISTS: {path_exists}")

    if getattr(sys, "frozen", False) or not path_exists:
        print("\n\nGOT HERE")
        # Use extracted installer context resources
        return str(get_resource_dir(app_handle_).joinpath("binaries", "ms-playwright"))
    else:
        # Development override: Point straight to your static source project workspace files
        # instead of target/debug paths where files don't automatically copy
        print(f"\n\nParent Path: {Path(__file__).parents[2]}\n\n")
        return str(
            Path(__file__).parents[2].joinpath("binaries", "ms-playwright").resolve()
        )


async def start_network_heartbeat(app_handle_: AppHandle):
    global network_mgr
    network_mgr = NetworkManager(app_handle_)

    while True:
        # Check network configuration status every 15 seconds
        await network_mgr.check_connectivity()
        await asyncio.sleep(15)


def app_setup_hook() -> Callable[[AppHandle], None]:

    def _app_setup_hook(app_handle_: AppHandle) -> None:
        # 1. Calculate the active extracted location of bundled resources
        # PyTauri binds native path structures smoothly

        # 2. Inject environment dynamically to override defaults for this operation
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = resolve_browser_path(app_handle_)

        print(f"\n\nPLAYWRIGHT_BROWSERS_PATH: {os.environ['PLAYWRIGHT_BROWSERS_PATH']}")

        global app_handle
        app_handle = app_handle_

        # asyncio.run(start_network_heartbeat(app_handle_))

    return _app_setup_hook


@commands.command()
async def on_app_ready(app_handle: AppHandle) -> str:
    # Register the heartbeat task worker loop directly inside the main thread frame
    asyncio.create_task(start_network_heartbeat(app_handle))
    return "Ok"


def on_event(app_handle: AppHandle, run_event: RunEventType) -> None:
    # print("\n\nON_EVENT CALLED!!!!")

    # match run_event:
    #     case RunEvent.Ready:
    #         print("The application and window are ready!")
    return None


@commands.command()
async def greet(body: Person) -> str:
    return f"Hello, {body.name}! You've been greeted from Python {sys.version}!"


@commands.command()
async def import_novel(body: ImportPayload, app_handle: AppHandle) -> NovelMetadata:
    Emitter.emit(app_handle, "test-event", ImportPayload(url=body.url))
    network_mgr = NetworkManager(app_handle)
    scraper = scraper_registry.get_scraper_for_url(body.url)

    # # 2. Get network manager (Assuming it is globally initialized as shown previously)
    # # Fetch raw HTML content through our anti-ban proxy/throttler engine

    # # 3. Parse the layout safely over C-memory speed structures
    metadata = await scraper.parse_metadata(body.url, network_mgr)

    # # Return structured dict back to your frontend UI
    # return metadata.model_dump()
    return metadata


def main() -> int:
    with start_blocking_portal("asyncio") as portal:  # or `trio`
        app = builder_factory().build(
            context=context_factory(),
            invoke_handler=commands.generate_handler(portal),
            setup=app_setup_hook(),
        )

        exit_code = app.run_return(on_event)
        return exit_code
