"""
Bridging a synchronous Tauri callback (window close) into pytauri's anyio
runtime, so it can safely call our async shutdown().

The problem: Listener callbacks run on the main thread / Tauri's Rust
tokio runtime — never inside pytauri's anyio event loop. `shutdown()` is
`async def` and touches `manager`/`network_mgr`, both of which assume
they're running inside that anyio loop. You can't just call
`await shutdown()` from a plain sync callback — there's no running loop
to await against in that thread.

The fix: AsyncTools.to_sync wraps an async function into a plain sync
callable. Under the hood it uses the anyio BlockingPortal to schedule the
coroutine onto the anyio loop's thread and blocks the calling (sync)
thread until it finishes — which is exactly the shape Listener expects.
"""

from pytauri import AppHandle, Event, Listener
from pytauri_utils.async_tools import AsyncTools

from backend.app import shutdown


def register_shutdown_listener(app_handle: AppHandle, async_tools: AsyncTools) -> None:
    """Call this once during app setup (see main.py below) — registers a
    one-shot listener for the window close event that runs our async
    shutdown() safely."""

    @async_tools.to_sync
    async def on_close_requested(event: Event) -> None:
        await shutdown()

    # "tauri://close-requested" is Tauri's built-in window-close event name.
    # Listener.once auto-unregisters after firing, which is what you want
    # for a shutdown hook — it should only ever run once.
    Listener.once(app_handle, "tauri://close-requested", on_close_requested)


# --- where this actually gets wired up: see __init__.py -------------------
#
# register_shutdown_listener(app_handle, async_tools) is called once from
# main.py, right after Manager.manage(app, async_tools) and app.handle() —
# see main.py for the full sequence.
