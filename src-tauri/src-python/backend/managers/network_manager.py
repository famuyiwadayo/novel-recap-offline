"""
NetworkManager — replaces headless_client.py.

Wraps PlaywrightManager (the actual browser + context pool) and adds what an
offline-first app needs on top:

  - check_connectivity(): one-shot probe. Deliberately NOT an HTTP request —
    a raw TCP connect attempt to a well-known host:port. Cheap, no new
    dependency (socket is stdlib), and works even before any browser context
    exists.
  - wait_until_online(): any fetch blocks gracefully during a brief outage
    instead of immediately failing and burning a retry.
  - on_connectivity_change(cb): listeners (sync or async) get called on every
    online<->offline transition — this is what lets the task queue pause
    when connectivity drops and resume (+ retry dead tasks) when it's back.
  - fetch_html() / page(): what vendor scrapers actually call. BaseScraper's
    signatures don't change — parse_metadata/parse_chapter still just
    receive `network_mgr` opaquely; only what it does internally is new.
"""

from __future__ import annotations

import inspect
import socket
import anyio
from anyio import to_thread
from contextlib import asynccontextmanager
from typing import Any, Callable, List, Optional, Literal

from playwright_stealth import Stealth

from .playwright_manager import PlaywrightManager

ConnectivityListener = Callable[[bool], Any]  # bool = now online; sync or async


async def _call_maybe_async(cb: Callable, *args) -> None:
    if inspect.iscoroutinefunction(cb):
        await cb(*args)
    else:
        cb(*args)


def _tcp_probe(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class NetworkManager:
    def __init__(
        self,
        playwright_manager: PlaywrightManager,
        probe_host: str = "1.1.1.1",
        probe_port: int = 443,
        probe_timeout: float = 3.0,
        poll_interval: float = 10.0,
    ) -> None:
        self._pw = playwright_manager
        self._probe_host = probe_host
        self._probe_port = probe_port
        self._probe_timeout = probe_timeout
        self._poll_interval = poll_interval

        self._is_online = (
            True  # optimistic default until the first check says otherwise
        )
        self._online_event = anyio.Event()
        self._online_event.set()
        self._listeners: List[ConnectivityListener] = []
        self._monitor_scope: Optional[anyio.CancelScope] = None
        self._stealth = Stealth()

    # --- connectivity -------------------------------------------------------

    @property
    def is_online(self) -> bool:
        return self._is_online

    def on_connectivity_change(self, cb: ConnectivityListener) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    async def check_connectivity(self) -> bool:
        """One-shot probe. Runs the blocking socket call in a worker thread
        so it never blocks the event loop."""
        return await to_thread.run_sync(
            _tcp_probe, self._probe_host, self._probe_port, self._probe_timeout
        )

    async def wait_until_online(self) -> None:
        await self._online_event.wait()

    async def _set_online(self, value: bool) -> None:
        if value == self._is_online:
            return
        self._is_online = value
        if value:
            self._online_event.set()
        else:
            self._online_event = (
                anyio.Event()
            )  # fresh, unset — next wait_until_online() blocks
        for cb in list(self._listeners):
            await _call_maybe_async(cb, value)

    async def start_monitoring(self) -> None:
        """Runs forever (until stop_monitoring()). Start this once alongside
        your other long-lived app startup tasks."""
        with anyio.CancelScope() as scope:
            self._monitor_scope = scope
            while True:
                online = await self.check_connectivity()
                await self._set_online(online)
                await anyio.sleep(self._poll_interval)

    def stop_monitoring(self) -> None:
        if self._monitor_scope is not None:
            self._monitor_scope.cancel()

    # --- browser-backed fetching ---------------------------------------------
    # Everything below blocks on wait_until_online() first — belt-and-suspenders
    # alongside the poll loop, in case a fetch starts in the gap right before
    # a transition is detected.

    async def fetch_html(
        self,
        url: str,
        wait_until: Optional[
            Literal["commit", "domcontentloaded", "load", "networkidle"]
        ] = "domcontentloaded",
        timeout_ms: int = 30_000,
    ) -> str:
        await self.wait_until_online()
        ctx = await self._pw.acquire_context()
        await self._stealth.apply_stealth_async(ctx)

        try:
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                return await page.content()
            finally:
                await page.close()
        finally:
            await self._pw.release_context(ctx)

    @asynccontextmanager
    async def page(
        self,
        url: str,
        wait_until: Optional[
            Literal["commit", "domcontentloaded", "load", "networkidle"]
        ] = "domcontentloaded",
        timeout_ms: int = 30_000,
    ):
        """For scrapers that need more than raw HTML — selectors, waits,
        page.evaluate(), etc.:

            async with network_mgr.page(url) as pg:
                await pg.wait_for_selector("#chapter-content")
                text = await pg.inner_text("#chapter-content")
        """
        await self.wait_until_online()
        ctx = await self._pw.acquire_context()
        await self._stealth.apply_stealth_async(ctx)

        try:
            pg = await ctx.new_page()
            try:
                await pg.goto(url, wait_until=wait_until, timeout=timeout_ms)
                yield pg
            finally:
                await pg.close()
        finally:
            await self._pw.release_context(ctx)
