import os
import sys

from pathlib import Path
from anyio.from_thread import start_blocking_portal
from pydantic import BaseModel
from collections.abc import Callable

from pytauri.path import PathResolver
from pytauri import (
    AppHandle,
    # RunEvent,
    Manager,
    RunEventType,
    builder_factory,
    context_factory,
)
from pytauri_utils.async_tools import AsyncTools

from backend.commands import commands
from backend.app import manager, network_mgr, wire_events, startup
from backend.shutdown_listener import register_shutdown_listener


app_handle: AppHandle


class ImportPayload(BaseModel):
    url: str


def get_resource_dir(app_handle_: AppHandle) -> Path:
    path_resolver: PathResolver = Manager.path(app_handle_)
    return path_resolver.resource_dir()


def get_app_data_dir(app_handle_: AppHandle) -> Path:
    path_resolver: PathResolver = Manager.path(app_handle_)
    return path_resolver.app_data_dir()


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


def on_event(app_handle: AppHandle, run_event: RunEventType) -> None:
    # print("\n\nON_EVENT CALLED!!!!")

    # match run_event:
    #     case RunEvent.Ready:
    #         print("The application and window are ready!")
    return None


# @commands.command()
# async def import_novel(body: ImportPayload, app_handle: AppHandle) -> NovelMetadata:
#     Emitter.emit(app_handle, "test-event", ImportPayload(url=body.url))
#     network_mgr = NetworkManager(app_handle)
#     scraper = scraper_registry.get_scraper_for_url(body.url)

#     # # 2. Get network manager (Assuming it is globally initialized as shown previously)
#     # # Fetch raw HTML content through our anti-ban proxy/throttler engine

#     # # 3. Parse the layout safely over C-memory speed structures
#     metadata = await scraper.parse_metadata(body.url, network_mgr)

#     # # Return structured dict back to your frontend UI
#     # return metadata.model_dump()
#     return metadata


def main() -> int:
    with (
        start_blocking_portal(
            "asyncio"
        ) as portal,  # pytauri backend — must be "asyncio", not "trio"
        AsyncTools(portal) as async_tools,
    ):
        app = builder_factory().build(
            context=context_factory(),
            invoke_handler=commands.generate_handler(portal),
            setup=app_setup_hook(),
        )

        # makes AsyncTools resolvable via Annotated[AsyncTools, State()] in
        # any @commands.command() that still wants it directly
        Manager.manage(app, async_tools)

        app_handle = app.handle()

        # 1. register event-forwarding listeners — plain sync call
        wire_events(app_handle)

        # 2. BLOCK until the browser is actually up, before the app starts
        #    accepting IPC calls — this is what removes the race a
        #    fire-and-forget start would otherwise have (a command hitting
        #    network_mgr.page() before pw_manager.start() finished)
        portal.call(startup)

        # 3. these run forever — fire-and-forget via the portal (NOT
        #    task_group.start_soon, which only works from inside an
        #    already-running coroutine; portal.start_task_soon is the
        #    equivalent callable from synchronous code)
        portal.start_task_soon(manager.start)
        portal.start_task_soon(network_mgr.start_monitoring)

        register_shutdown_listener(app_handle, async_tools)

        exit_code = app.run_return(on_event)
        return exit_code
