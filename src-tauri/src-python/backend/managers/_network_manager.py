import asyncio
import random
import httpx
from pytauri import AppHandle

from backend.managers.headless_client import HeadlessBrowserManager


class NetworkManager:
    def __init__(self, app_handle: AppHandle):
        self.app_handle = app_handle
        self.is_online = True
        self.request_delay = 2.0  # Base delay in seconds between scraping requests
        self.headless_mgr = HeadlessBrowserManager()

        # Rotated headers to avoid fingerprinting
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
        ]

        # Shared HTTP client with connection pooling
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )

    def get_stealth_headers(self) -> dict:
        """Generates look-alike browser headers to evade basic scrapers blocks."""

        return {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    async def check_connectivity(self) -> bool:
        """Pings a reliable server to check true offline/online state changes."""
        try:
            # Quick ping check using a standard cloudflare endpoint
            response = await self.client.get("https://1.1.1", timeout=3.0)
            new_state = response.status_code == 200
        except (httpx.HTTPError, OSError):
            new_state = False

        if new_state != self.is_online:
            self.is_online = new_state
            # Broadcast state changes globally to frontend UI components
            # self.app_handle.emit("network-status-changed", {"online": self.is_online})
            print(
                f"📡 Network connection flipped: {'ONLINE' if self.is_online else 'OFFLINE'}"
            )

        return self.is_online

    async def safe_get_html(self, url: str, max_retries: int = 3) -> str:
        """
        Executes an HTTP GET request with automated online-state checking,
        anti-ban throttling, and exponential backoff retry fallbacks.
        """
        retries = 0
        backoff = 2.0

        while True:
            # 1. Enforce offline block if network state drops
            while not self.is_online:
                print(
                    "⏳ Scraper paused. Waiting for internet connection to recover..."
                )
                await asyncio.sleep(5)
                await self.check_connectivity()

            # 2. Enforce an intentional delay to prevent rate-limiting bans
            # Adds ±0.5s jitter so patterns look organic
            actual_delay = self.request_delay + random.uniform(-0.5, 0.5)
            await asyncio.sleep(max(0.1, actual_delay))

            try:
                response = await self.client.get(
                    url, headers=self.get_stealth_headers()
                )

                # Check for anti-bot or server overload blocks
                if response.status_code == 429:
                    print("⚠️ Rate limited (429). Increasing delay parameters...")
                    self.request_delay += 1.0  # Dynamically slow down further hits
                    raise httpx.HTTPStatusError(
                        "Rate Limit Blocked",
                        request=response.request,
                        response=response,
                    )

                response.raise_for_status()
                return response.text

            except (httpx.HTTPError, OSError) as err:
                retries += 1
                if retries > max_retries:
                    print(f"❌ Permanent scraping failure for URL: {url}")
                    await self.check_connectivity()  # Verify if network died completely
                    raise err

                print(
                    f"🔄 Network glitch ({err}). Retrying block {retries}/{max_retries} in {backoff}s..."
                )
                await asyncio.sleep(backoff)
                backoff *= 2.0  # Double retry timer length sequentially

    async def fetch_html_with_fallback(self, url: str, target_selector: str = "p"):
        """Tries a standard fast HTTP fetch first. Falls back to Playwright if needed."""
        try:
            # 1. Attempt standard lightweight stealth fetch
            html = await self.safe_get_html(url)

            # Verify if text contents were returned or blocked by checking for standard elements
            if "captcha" in html.lower() or "<p>" not in html.lower():
                raise ValueError("Anti-bot block or JavaScript rendering detected.")

            return html

        except Exception as e:
            print(
                f"⚠️ Standard fetch blocked or failed: {e}. Activating Playwright browser engine..."
            )
            # 2. Trigger browser rendering mode to parse through JS blocks safely
            return await self.headless_mgr.scrape_dynamic_page(
                url, wait_for_selector=target_selector
            )

    async def fetch_with_browser_interaction(
        self, url: str, interaction_callback=None
    ) -> str | None:
        """
        Launches Playwright, navigates to the page, executes an optional
        custom callback (like clicking tabs), and harvests the final DOM.
        """
        await self.headless_mgr.initialize()

        if self.headless_mgr.browser:
            context = await self.headless_mgr.browser.new_context(
                user_agent=random.choice(self.user_agents),
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)

                # If the specific scraper passed a tab-toggling instruction, execute it now
                if interaction_callback:
                    await interaction_callback(page)
                    # Give JavaScript a brief window to animate or hydrate the new layout
                    await page.wait_for_timeout(800)

                return await page.content()
            finally:
                await page.close()
                await context.close()
