"""
Generic (non-scraper-specific) plugins for task_queue.TaskQueueManager.

Scraper-specific plugins now live in task_plugins.py (registry-driven —
resolves the right vendor scraper per URL via backend/scrapers/registry.py).
The site-specific NovelDiscoveryPlugin/ChapterFetchPlugin and their
Playwright variants that used to live here are superseded by that and have
been removed; task_plugins.py is what app_wiring.py actually registers.

ImageDownloadPlugin stays here since it's genuinely generic — useful for
cover art or any other binary asset, independent of which scraper produced
the URL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from anyio import to_thread

from backend.managers.task_queue import Plugin, PluginResult, ProgressFn, Task


FetchBytesStreaming = Callable[[str, ProgressFn], bytes]
"""A blocking function: (url, report_progress) -> raw bytes.
report_progress should be called with (fraction_done, message) as bytes
arrive if the source supports it (e.g. from a requests stream + Content-Length)."""


def _default_fetch_bytes_streaming(url: str, report_progress: ProgressFn) -> bytes:
    """Default blocking implementation using `requests`, streaming with
    progress based on Content-Length (falls back to indeterminate progress
    if the server doesn't send one)."""
    import requests

    chunks = []
    with requests.get(url, stream=True, timeout=30) as resp:
        resp.raise_for_status()
        total = resp.headers.get("Content-Length")
        total = int(total) if total else None
        downloaded = 0
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            chunks.append(chunk)
            downloaded += len(chunk)
            if total:
                report_progress(
                    downloaded / total, f"{downloaded // 1024}KB / {total // 1024}KB"
                )
            else:
                report_progress(0.0, f"{downloaded // 1024}KB")
    return b"".join(chunks)


@dataclass
class ImageDownloadPayload:
    url: str
    dest_path: str
    overwrite: bool = False


class ImageDownloadPlugin(Plugin):
    """Generic image (or any binary file) downloader. Task.payload should
    be an ImageDownloadPayload (or a dict with the same keys)."""

    kind = "image_download"

    def __init__(
        self,
        fetch_bytes_streaming: FetchBytesStreaming = _default_fetch_bytes_streaming,
    ) -> None:
        self._fetch = fetch_bytes_streaming

    async def run(self, task: Task, report_progress: ProgressFn) -> PluginResult:
        payload = task.payload
        if isinstance(payload, dict):
            payload = ImageDownloadPayload(**payload)

        if os.path.exists(payload.dest_path) and not payload.overwrite:
            report_progress(1.0, "already exists, skipped")
            return PluginResult(data={"path": payload.dest_path, "skipped": True})

        os.makedirs(os.path.dirname(payload.dest_path) or ".", exist_ok=True)
        data = await to_thread.run_sync(self._fetch, payload.url, report_progress)

        tmp_path = payload.dest_path + ".part"
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, payload.dest_path)

        return PluginResult(
            data={"path": payload.dest_path, "bytes": len(data), "skipped": False}
        )
