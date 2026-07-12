"""
Adapter plugins wiring backend/scrapers/registry.py + backend/scrapers/base.py
into task_queue.TaskQueueManager. Matches the real BaseScraper interface:

    class BaseScraper(BaseModel):
        target_domain: str                              # abstract property
        def can_handle(self, url: str) -> bool           # INSTANCE method
        async def parse_metadata(self, source_url: str, network_mgr) -> NovelMetadata
        async def parse_chapter(self, novel_id, chapter_url: str, chapter_num: int, network_mgr) -> ExtractedChapter

Because can_handle is an instance method (reads self.target_domain), your
registry necessarily holds already-instantiated scrapers loaded from
scrapers/vendors/ — not classes it instantiates per call. resolve() below
is assumed to return one such instance (or None); rename the call if your
registry.py exposes something else (get_scraper / match / find...).

network_mgr is opaque here — this module doesn't know or care whether it's
plain requests/httpx or wraps headless_client.py internally for JS-heavy
pages. It's constructed once wherever you wire this up and passed straight
through to every scraper call.

Two things are NOT this module's job, on purpose:
  - Browser/session lifecycle — that's inside network_mgr / headless_client.py.
  - Anti-scraper content cleanup (is_node_hidden_by_css etc.) — that's
    inside each vendor scraper's parse_chapter, already handled before the
    ExtractedChapter comes back to us.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional, Any, Protocol, Union, runtime_checkable

from anyio import to_thread

from backend.managers.task_queue import Plugin, PluginResult, ProgressFn, Task


# ============================================================================
# Adapter protocols — line these up with your actual base.py / registry.py
# ============================================================================


@runtime_checkable
class ScraperLike(Protocol):
    async def parse_metadata(
        self,
        source_url: str,
        network_mgr: Any,
        *,
        report_progress: ProgressFn,
    ) -> Any: ...
    async def parse_chapter(
        self,
        novel_id: Any,
        chapter_url: str,
        chapter_num: int,
        network_mgr: Any,
        *,
        report_progress: ProgressFn,
    ) -> Any: ...


@runtime_checkable
class RegistryLike(Protocol):
    def get_scraper_for_url(self, url: str) -> ScraperLike: ...

    # rename this call below if registry.py's lookup method has a different name


class NoScraperFound(Exception):
    """No registered vendor scraper's can_handle() matched the URL. This is
    a PERMANENT failure, not a transient one — retrying won't make a new
    scraper appear. Consider enqueuing with max_retries=0 for discovery/
    chapter tasks if you'd rather this dead-letter immediately."""


# ============================================================================
# Task payloads
# ============================================================================


@dataclass
class NovelDiscoveryPayload:
    novel_id: Union[int, str]
    source_url: str
    chapter_priority_base: int = (
        0  # chapters get priority = base + index, keeps reading order under contention
    )


@dataclass
class ChapterFetchPayload:
    novel_id: Union[int, str]
    chapter_url: str
    chapter_num: int  # 1-indexed position in NovelMetadata.chapter_urls


# ============================================================================
# Persistence — replace with a DB write if that's where ExtractedChapter goes
# ============================================================================


def _default_persist_chapter(chapter: Any) -> None:
    """chapter is an ExtractedChapter (novel_id, chapter_number, title, content, source_url)."""
    safe_title = re.sub(r"[^\w\-. ]", "_", chapter.title)[:80]
    dir_path = os.path.join("scraped", str(chapter.novel_id))
    os.makedirs(dir_path, exist_ok=True)
    path = os.path.join(dir_path, f"{chapter.chapter_number:04d}_{safe_title}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(chapter.content)


# ============================================================================
# Plugins
# ============================================================================


class RegistryNovelDiscoveryPlugin(Plugin):
    kind = "novel_discovery"

    def __init__(
        self, registry: RegistryLike, network_mgr: Any, chapter_max_retries: int = 3
    ) -> None:
        self._registry = registry
        self._network_mgr = network_mgr
        self._chapter_max_retries = chapter_max_retries

    async def run(self, task: Task, report_progress: ProgressFn) -> PluginResult:
        payload = task.payload
        if isinstance(payload, dict):
            payload = NovelDiscoveryPayload(**payload)

        report_progress(0.0, "Resolving scraper...")
        scraper = self._registry.get_scraper_for_url(payload.source_url)
        if scraper is None:
            raise NoScraperFound(f"No scraper registered for {payload.source_url!r}")

        report_progress(0.1, f"Using {type(scraper).__name__}")
        metadata = await scraper.parse_metadata(
            payload.source_url, self._network_mgr, report_progress=report_progress
        )
        report_progress(1.0, f"Found {len(metadata.chapter_urls)} chapters")

        children = [
            Task(
                kind="chapter_fetch",
                payload=ChapterFetchPayload(
                    novel_id=payload.novel_id,
                    chapter_url=url,
                    chapter_num=i
                    + 1,  # matches BaseScraper.parse_chapter's 1-indexed chapter_num
                ),
                priority=payload.chapter_priority_base + i,
                group=str(payload.novel_id),
                max_retries=self._chapter_max_retries,
            )
            for i, url in enumerate(metadata.chapter_urls)
        ]
        return PluginResult(data=metadata, spawn=children)


class RegistryChapterFetchPlugin(Plugin):
    kind = "chapter_fetch"

    def __init__(
        self,
        registry: RegistryLike,
        network_mgr: Any,
        persist_chapter=_default_persist_chapter,
    ) -> None:
        self._registry = registry
        self._network_mgr = network_mgr
        self._persist_chapter = persist_chapter

    async def run(self, task: Task, report_progress: ProgressFn) -> PluginResult:
        payload = task.payload
        if isinstance(payload, dict):
            payload = ChapterFetchPayload(**payload)

        report_progress(0.0, f"Resolving scraper for chapter {payload.chapter_num}")
        scraper = self._registry.get_scraper_for_url(payload.chapter_url)
        if scraper is None:
            raise NoScraperFound(f"No scraper registered for {payload.chapter_url!r}")

        chapter = await scraper.parse_chapter(
            payload.novel_id,
            payload.chapter_url,
            payload.chapter_num,
            self._network_mgr,
            report_progress=report_progress,
        )
        # persistence is blocking file/DB I/O — offload, doesn't touch network_mgr
        await to_thread.run_sync(self._persist_chapter, chapter)
        report_progress(1.0, "done")

        # deliberately NOT returning chapter.content in result.data — it can
        # be large and it's already persisted; keep the queue's footprint small
        return PluginResult(
            data={"title": chapter.title, "chars": len(chapter.content)}
        )
