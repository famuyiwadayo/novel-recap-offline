# import random
import asyncio

from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser

from backend.scrapers.base import BaseScraper, NovelMetadata, ExtractedChapter
from backend.managers.network_manager import NetworkManager


class WtrLabScraper(BaseScraper):
    @property
    def target_domain(self) -> str:
        return "wtr-lab.com"

    def can_handle(self, url):
        return super().can_handle(url)

    async def parse_metadata(self, source_url, network_mgr: NetworkManager):
        # Define a custom page-interaction script for this specific site structure

        title: str = ""
        other_title: str = ""
        cover_image_url: str | None = None
        total_chapters = 0
        tags: list[str] = []

        author: str = ""
        status: str | None = None
        other_author_name: str = ""

        parsed = urlparse(source_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        html_content, raw_chapter_links = await self.fetch_main_page_html_contents(
            source_url, network_mgr
        )

        if not html_content:
            raise ValueError("Failed to retrieve HTML content from the page")

        if not raw_chapter_links:
            raise ValueError("Failed to retrieve chapter links from the page")

        # html_content = results.
        # Pass raw HTML text string down into the lightning-fast Lexbor C-engine

        tree = LexborHTMLParser(html_content)

        card_content = tree.css_first(".p-2[data-slot='card-content']")

        titlebox = card_content.child
        statusbox = card_content.child.next if card_content.child else None
        tagbox = card_content.last_child
        detailbox = tree.css_first(".p-2[data-slot='card-content'].chapter-details")

        if titlebox:
            title = titlebox.css_first("h1").text()
            other_title = titlebox.css_first("p").text()

        if statusbox:
            cover_image_url = statusbox.css_first("img").attributes["src"]
            chapter_count = statusbox.css_first(
                "span[translate='no']:lexbor-contains('chapters'i)"
            ).next
            total_chapters = int(chapter_count.text()) if chapter_count else 0

        tags = [tag.text().lower() for tag in tagbox.css("span")] if tagbox else []
        summary = detailbox.css_first(".desc-wrap > span.description").text()

        detailgrid_parent = (
            detailbox.css_first("[data-slot='tabs-content']")
            .css_first("span:lexbor-contains('details'i)")
            .parent
        )
        detailgrid = detailgrid_parent.next if detailgrid_parent else None

        if detailgrid:
            status_element = detailgrid.css_first(":lexbor-contains('status'i)").next
            author_element = detailgrid.css_first(":lexbor-contains('author'i)").next

            status = status_element.text() if status_element else None
            author = (
                author_element.child.text()
                if author_element and author_element.child
                else "unknown"
            )

            other_author_name = (
                author_element.last_child.text()
                if author_element and author_element.last_child
                else "unknown"
            )

        links = [f"{base_url}/{x}" for x in raw_chapter_links]

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
        self, novel_id, chapter_url, chapter_num, network_mgr
    ) -> ExtractedChapter:
        return await super().parse_chapter(
            novel_id, chapter_url, chapter_num, network_mgr
        )

    async def fetch_main_page_html_contents(
        self, url: str, network_mgr: NetworkManager
    ):
        # instance = network_mgr.headless_mgr
        initial_html_content: str = ""
        chapters: list[str] = []
        # context = None
        # page = None

        async with network_mgr.page(url) as pg:
            try:
                # await instance.initialize()
                # browser = instance.browser

                # if not browser:
                #     return "", []

                # context = await browser.new_context(
                #     user_agent=random.choice(network_mgr.user_agents),
                #     viewport={"width": 1280, "height": 800},
                # )

                # page = await context.new_page()

                # Navigate to the target web novel page URL
                await pg.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Explicitly wait for javascript text frameworks to finish rendering elements into DOM
                await pg.wait_for_selector(".chapter-details", timeout=60000)

                initial_html_content = await pg.content()

                tab = pg.get_by_role("tab", name="Table of Contents")
                await asyncio.sleep(1)
                await tab.click()
                await pg.wait_for_selector(".chapter-list", timeout=10000)

                accordion_items = pg.locator("div[data-slot='accordion-item']")
                count = await accordion_items.count()
                print(f"[+] Found {count} accordion panels to expand.")

                accordions = await accordion_items.all()

                if count > 0:
                    for idx, item in enumerate(accordions):
                        data_index = await item.get_attribute("data-index")
                        print(
                            f"[+] Processing accordion index: {data_index} (Loop index: {idx})"
                        )

                        trigger = item.locator("button[data-slot='accordion-trigger']")
                        await trigger.click()

                        anchor_elements = item.locator(
                            "div[data-slot='accordion-content'] a"
                        )

                        try:
                            await anchor_elements.first.wait_for(
                                state="attached", timeout=5000
                            )
                        except Exception:
                            print(
                                f"[!] Warning: No links appeared in accordion {idx} after 5 seconds."
                            )

                        for a in await anchor_elements.all():
                            link = await a.get_attribute("href")
                            if link:
                                chapters.append(link)

                        await asyncio.sleep(1)

                return initial_html_content, chapters

            except Exception as exc:
                print(f"[!] Failed to fetch HTML contents: {exc}")
                return "", []

            # finally:
            #     if page is not None:
            #         await page.close()
            #     if context is not None:
            #         await context.close()
            #     await instance.shutdown()
