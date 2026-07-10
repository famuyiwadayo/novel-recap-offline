"""
Shared Playwright (async API) lifecycle manager.

Why this exists: launching a browser is expensive, and launching one per
task would defeat the point of a concurrent task queue. This starts ONE
browser for the whole app's lifetime, and hands out browser *contexts*
(isolated cookie/storage sessions) to tasks from a bounded, reusable pool.

Uses Playwright's ASYNC API deliberately — the sync API cannot run inside
an already-active asyncio event loop (it manages its own thread + loop
internally), but our task_queue plugins already run as `async def` inside
one. Calling the async API directly here means no extra threads, no
per-task browser startup cost, and natural integration with anyio's
event loop and cancellation.

Concurrency is bounded by a semaphore, not just "however many tasks show
up" — acquire_context() blocks until a slot is free, so this composes
correctly with TaskQueueManager's own concurrency (num_workers can safely
exceed max_contexts; workers will just wait their turn for a browser
context, the same way they'd wait on any other bounded resource).
"""

from __future__ import annotations

from typing import List, Optional

import anyio
from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright


class PlaywrightManager:
    def __init__(self, headless: bool = True, max_contexts: int = 5) -> None:
        self._headless = headless
        self._max_contexts = max_contexts
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._semaphore = anyio.Semaphore(max_contexts)
        self._available: List[BrowserContext] = []
        self._pool_lock = anyio.Lock()

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        # channel="chromium" here to opt into the same engine as chromium-headless-shell
        # by default; swap to channel="msedge" if you want to piggyback on a
        # system-installed Edge instead of bundling a browser at all.
        self._browser = await self._playwright.chromium.launch(headless=self._headless)

    async def stop(self) -> None:
        async with self._pool_lock:
            for ctx in self._available:
                await ctx.close()
            self._available.clear()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def acquire_context(self, **new_context_kwargs) -> BrowserContext:
        """Blocks until a context slot is free (bounded concurrency), then
        returns a reused context if one's available, else creates a new one."""
        await self._semaphore.acquire()
        try:
            async with self._pool_lock:
                if self._available:
                    return self._available.pop()
            assert self._browser is not None, "PlaywrightManager.start() not called yet"
            return await self._browser.new_context(**new_context_kwargs)
        except BaseException:
            # we acquired the semaphore but failed (or were cancelled) before
            # getting a usable context back to the caller — give the slot back
            self._semaphore.release()
            raise

    async def release_context(
        self, ctx: BrowserContext, *, discard: bool = False
    ) -> None:
        """Return a context to the pool for reuse. Pass discard=True if the
        context's state got messy (e.g. you're not confident cookies/storage
        are clean) and it should be closed instead of reused.

        Shielded from cancellation: if the caller's task was just cancelled
        (e.g. via TaskQueueManager.cancel()), this still needs to finish
        releasing the slot — otherwise a cancelled task leaks its context
        forever and every future acquire_context() call for that slot hangs."""
        with anyio.CancelScope(shield=True):
            if discard:
                await ctx.close()
            else:
                async with self._pool_lock:
                    self._available.append(ctx)
            self._semaphore.release()

    @property
    def in_use(self) -> int:
        return self._max_contexts - self._semaphore.value
