import asyncio

from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser, LexborNode

from backend.managers.task_queue import ProgressFn
from backend.managers.network_manager import NetworkManager
from backend.scrapers.base import BaseScraper, NovelMetadata, ExtractedChapter


def _require(node: LexborNode | None, selector: str, what: str) -> LexborNode:
    """css_first that raises a clear, specific error instead of letting a
    None propagate into the next .css_first()/.next/.text() call as an
    opaque AttributeError. Use for fields the scrape can't meaningfully
    continue without (title, chapter links, the containers themselves)."""
    if node is None:
        raise ValueError(f"Could not find {what} — parent node was None")
    found = node.css_first(selector)
    if found is None:
        raise ValueError(f"Could not find {what} (selector: {selector!r})")
    return found


def _optional_text(node: LexborNode | None, default: str = "") -> str:
    """For cosmetic/non-critical fields (tags, other titles, author names)
    — a missing element shouldn't crash the whole scrape, just fall back."""
    if node is None:
        return default
    text = node.text()
    return text if text else default


class WtrLabScraper(BaseScraper):
    @property
    def target_domain(self) -> str:
        return "wtr-lab.com"

    async def parse_metadata(
        self, source_url, network_mgr: NetworkManager, *, report_progress: ProgressFn
    ):
        parsed = urlparse(source_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        # fetch_main_page_html_contents no longer swallows exceptions and
        # return ("", []) sentinels — real failures now propagate with
        # their actual cause, so there's nothing to check-and-re-raise here
        # anymore; if this call returns, the content is real.
        html_content, raw_chapter_links = await self.fetch_main_page_html_contents(
            source_url, network_mgr, report_progress
        )

        tree = LexborHTMLParser(html_content)

        card_content = _require(
            tree, ".p-2[data-slot='card-content']", "the main card content block"
        )
        titlebox = card_content.child
        statusbox = card_content.child.next if card_content.child else None
        tagbox = card_content.last_child
        detailbox = tree.css_first(".p-2[data-slot='card-content'].chapter-details")

        # --- required: without a title, the metadata isn't usable ---
        report_progress(0.65, "Extracting novel title...")
        title_el = _require(titlebox, "h1", "the novel title")
        title = title_el.text()
        other_title = _optional_text(titlebox.css_first("p") if titlebox else None)

        # --- optional: cover image / chapter count — soft-fail to sensible defaults ---
        report_progress(0.68, "Extracting cover image...")
        cover_image_url: str | None = None
        total_chapters = 0
        if statusbox is not None:
            img_el = statusbox.css_first("img")
            if img_el is not None:
                cover_image_url = img_el.attributes.get("src")

            chapter_count_label = statusbox.css_first(
                "span[translate='no']:lexbor-contains('chapters'i)"
            )
            chapter_count = chapter_count_label.next if chapter_count_label else None
            if chapter_count is not None:
                try:
                    total_chapters = int(chapter_count.text().strip().replace(",", ""))
                except (ValueError, AttributeError):
                    total_chapters = 0  # non-critical — malformed/unexpected text shouldn't crash the scrape

        # --- optional: tags / summary ---
        report_progress(0.72, "Extracting tags and summary...")
        tags = [t.text().lower() for t in tagbox.css("span")] if tagbox else []
        summary = ""
        if detailbox is not None:
            summary_el = detailbox.css_first(".desc-wrap > span.description")
            summary = _optional_text(summary_el)

        # --- optional: status / author — guard every hop, don't hard-fail on cosmetic fields ---
        status: str | None = None
        author = "unknown"
        other_author_name = "unknown"
        if detailbox is not None:
            tabs_content = detailbox.css_first("[data-slot='tabs-content']")
            details_label = (
                tabs_content.css_first("span:lexbor-contains('details'i)")
                if tabs_content is not None
                else None
            )
            detailgrid_parent = (
                details_label.parent if details_label is not None else None
            )
            detailgrid = (
                detailgrid_parent.next if detailgrid_parent is not None else None
            )

            if detailgrid is not None:
                report_progress(0.8, "Extracting status and author info...")
                status_label = detailgrid.css_first(":lexbor-contains('status'i)")
                author_label = detailgrid.css_first(":lexbor-contains('author'i)")
                status_element = status_label.next if status_label is not None else None
                author_element = author_label.next if author_label is not None else None

                status = _optional_text(status_element, default=None)  # type: ignore[arg-type]
                author = _optional_text(
                    author_element.child if author_element else None, default="unknown"
                )
                other_author_name = _optional_text(
                    author_element.last_child if author_element else None,
                    default="unknown",
                )

        # --- required: no chapter links means this scrape produced nothing useful ---
        if not raw_chapter_links:
            raise ValueError(
                f"Found the novel page but no chapter links at {source_url!r}"
            )
        links = [f"{base_url}/{x}" for x in raw_chapter_links]
        report_progress(0.9, "Cleaning up chapter links...")

        return NovelMetadata(
            title=title,
            other_titles=[other_title],
            author=[author, other_author_name],
            tags=tags,
            status=status,
            summary=summary,
            cover_image_url=cover_image_url,
            total_chapters=total_chapters,
            chapter_urls=links,
        )

    async def parse_chapter(
        self,
        novel_id,
        chapter_url,
        chapter_num,
        network_mgr,
        *,
        report_progress: ProgressFn,
    ) -> ExtractedChapter:
        # Intentionally not implemented yet — parse_metadata/progress is
        # being finalized first. BaseScraper.parse_chapter is abstract with
        # `...` as its body, so this currently returns None rather than
        # raising or scraping anything; replace with real chapter parsing
        # when you get to this half.
        return await super().parse_chapter(
            novel_id,
            chapter_url,
            chapter_num,
            network_mgr,
            report_progress=report_progress,
        )

    async def fetch_main_page_html_contents(
        self, url: str, network_mgr: NetworkManager, report_progress: ProgressFn
    ) -> tuple[str, list[str]]:
        chapters: list[str] = []

        async with network_mgr.page(url) as pg:
            # No try/except here anymore — a real failure (navigation
            # timeout, selector never appearing, etc.) now propagates with
            # its actual exception/traceback instead of being converted
            # into a ("", []) sentinel that parse_metadata used to have to
            # re-interpret as a generic "failed to retrieve" error. The
            # task queue's normal retry/dead-letter handling deals with
            # this correctly either way — no need to catch it here too.
            await pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            await pg.wait_for_selector(".chapter-details", timeout=60000)

            initial_html_content = await pg.content()

            tab = pg.get_by_role("tab", name="Table of Contents")
            await asyncio.sleep(1)
            await tab.click()
            await pg.wait_for_selector(".chapter-list", timeout=10000)
            report_progress(0.2, "Checking chapters...")

            accordion_items = pg.locator("div[data-slot='accordion-item']")
            count = await accordion_items.count()
            accordions = await accordion_items.all()

            for idx, item in enumerate(accordions):
                # Scaled by the REAL accordion count, mapped into 0.2-0.6 —
                # deliberately capped well below 0.65 (the next checkpoint,
                # back in parse_metadata, which runs AFTER this function
                # returns). The old formula was `0.2 + (idx+1)/10`, which
                # assumed at most ~8 accordion groups; anything past that
                # (this scraper's own screenshot showed 689 chapters, very
                # likely >8 groups) pushed progress past 1.0, got clamped
                # to 100%, and then visibly regressed backward once the
                # real 0.65/0.68/.../0.9 checkpoints fired afterward.
                report_progress(
                    0.2 + 0.4 * (idx + 1) / max(count, 1), "Extracting chapters..."
                )

                trigger = item.locator("button[data-slot='accordion-trigger']")
                await trigger.click()

                anchor_elements = item.locator("div[data-slot='accordion-content'] a")

                try:
                    await anchor_elements.first.wait_for(state="attached", timeout=5000)
                except Exception:
                    # genuinely OK to continue here — an empty accordion
                    # group just contributes zero links, not a scrape failure
                    pass

                for a in await anchor_elements.all():
                    link = await a.get_attribute("href")
                    if link:
                        chapters.append(link)

                await asyncio.sleep(1)

            return initial_html_content, chapters
