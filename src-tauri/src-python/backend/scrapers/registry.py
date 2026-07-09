# python_backend/scrapers/registry.py
import os
import importlib
import inspect
from typing import Dict
from .base import BaseScraper


class ScraperRegistry:
    def __init__(self):
        self._registry: Dict[str, BaseScraper] = {}
        self._load_plugins()

    def _load_plugins(self):
        """Scans folder blocks and dynamically injects plugin strategies into tracking memory."""
        current_dir = os.path.dirname(__file__)

        for filename in os.listdir(f"{current_dir}/vendors"):
            # Skip base frameworks, registration cores, and compiled bytecode artifacts
            if (
                filename.startswith("__")
                or filename in ("base.py", "registry.py")
                or not filename.endswith(".py")
            ):
                continue

            module_name = f"backend.scrapers.vendors.{filename[:-3]}"
            try:
                module = importlib.import_module(module_name)

                # Look inside the module file for valid subclasses of BaseScraper
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseScraper) and obj is not BaseScraper:
                        scraper_instance = obj()
                        self._registry[scraper_instance.target_domain] = (
                            scraper_instance
                        )
                        print(
                            f"🔌 Successfully registered custom website scraper plugin: [{scraper_instance.target_domain}]"
                        )
            except Exception as e:
                print(
                    f"❌ Failed to load modular scraper plugin from file '{filename}': {e}"
                )

    def get_scraper_for_url(self, url: str) -> BaseScraper:
        """Matches a target URL to its designated custom scraper backend module."""
        for scraper in self._registry.values():
            if scraper.can_handle(url):
                return scraper
        raise ValueError(
            f"No custom scraper plugin registered capable of processing domain configuration for: {url}"
        )
