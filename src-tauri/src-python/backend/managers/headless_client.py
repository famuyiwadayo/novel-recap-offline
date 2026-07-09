from playwright.async_api import async_playwright, Browser, Playwright


class HeadlessBrowserManager:
    def __init__(self):
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None

    async def initialize(self):
        """launches a localize headless chromium browser instance"""
        if not self.browser:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"],
            )

    # async def scrape_dynamic_page(self, url: str, wait_for_selector: str = "p"):
    #     """Loads a page in a full browser environment, waits for elements to render, and pulls HTML."""

    #     await self.initialize()

    #     if self.browser:
    #         # Open an isolated browser tab context with desktop screen dimension mimicry
    #         context = await self.browser.new_context(
    #             user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    #             viewport={"width": 1280, "height": 800},
    #         )

    #         page = await context.new_page()
    #         try:
    #             # Navigate to the target web novel page URL
    #             await page.goto(url, wait_until="networkidle", timeout=30000)

    #             # Explicitly wait for javascript text frameworks to finish rendering elements into DOM
    #             await page.wait_for_selector(wait_for_selector, timeout=10000)

    #             # Extract the raw rendered HTML string code format
    #             html_content = await page.content()
    #             return html_content

    #         finally:
    #             await page.close()
    #             await context.close()

    async def scrape_dynamic_page(
        self, url: str, wait_for_selector: str = "p", use_page=False
    ):
        """
        Loads a page in a full browser environment, waits for elements to render, pulls HTML,
        and return a tuple of the HTML content and the browser page instance if use_page is True.
        NOTE: Owner must close the page after use.
        """

        await self.initialize()

        if self.browser:
            # Open an isolated browser tab context with desktop screen dimension mimicry
            context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )

            page = await context.new_page()

            try:
                # Navigate to the target web novel page URL
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # Explicitly wait for javascript text frameworks to finish rendering elements into DOM
                await page.wait_for_selector(wait_for_selector, timeout=10000)

                # Extract the raw rendered HTML string code format
                html_content = await page.content()

                return (html_content, page if use_page else None)

            finally:
                if not use_page:
                    await page.close()
                    await context.close()

    async def shutdown(self):
        """Closes browser background processes cleany on app exit."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
