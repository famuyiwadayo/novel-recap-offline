"""
backend/managers/app_paths.py

Single source of truth for where the app's files live on disk. Before
this existed, chapter content (task_plugins.py) and cover images
(app.py's cover-download wiring) each computed their own relative path
("scraped/...", "covers/...") independently — landing wherever the
process's current working directory happened to be when launched, with
no connection to the actual OS-appropriate app-data directory that
db_manager.py now correctly resolves via AppHandle. Same underlying
problem PLAYWRIGHT_BROWSERS_PATH had to solve for the browser binaries,
just for chapter/cover files instead.

Configured ONCE, in wire_events() (the earliest point AppHandle exists),
then read from anywhere that needs a path — db_manager, task_plugins.py's
persist_chapter, app.py's cover-download enqueue. Nothing downstream
constructs its own relative path anymore.

IMPORTANT: configure() mutates this instance IN PLACE — it does not do
`global app_paths; app_paths = AppPaths(...)`. That reassignment pattern
is exactly what caused the earlier `AssertionError('DBManager.start()
not called yet')` bug: any module that already did
`from backend.managers.app_paths import app_paths` at import time would
keep holding a stale reference to the original, unconfigured instance.
Mutating in place means every import of `app_paths`, from anywhere,
however early, is always looking at the same object.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Union


class AppPaths:
    def __init__(self) -> None:
        # Placeholder until configure() is called — mirrors DBManager's
        # own placeholder-then-set_db_path() pattern. Using this before
        # configure() runs will write into whatever the CWD happens to
        # be, same as the old behavior — configure() should be called
        # before anything actually needs to read/write files for real.
        self._app_data_dir: Path = Path("data")
        self.configured = False

    def configure(self, app_data_dir: Union[str, Path]) -> None:
        self._app_data_dir = Path(app_data_dir)
        self.configured = True
        # create these up front so nothing downstream needs to remember
        # its own mkdir(parents=True, exist_ok=True) call
        self.scraped_dir.mkdir(parents=True, exist_ok=True)
        self.covers_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def app_data_dir(self) -> Path:
        return self._app_data_dir

    @property
    def db_path(self) -> Path:
        return self._app_data_dir / "data" / "library.db"

    @property
    def scraped_dir(self) -> Path:
        return self._app_data_dir / "scraped"

    @property
    def covers_dir(self) -> Path:
        return self._app_data_dir / "covers"

    def chapter_path(self, novel_id: int, chapter_number: int, title: str) -> Path:
        safe_title = re.sub(r"[^\w\-. ]", "_", title or "untitled")[:80]
        return (
            self.scraped_dir / str(novel_id) / f"{chapter_number:04d}_{safe_title}.txt"
        )

    def cover_path(self, novel_id: int) -> Path:
        return self.covers_dir / f"{novel_id}.jpg"


# Module-level singleton — configure() mutates it; nothing ever reassigns
# this name. See the module docstring for exactly why that distinction matters.
app_paths = AppPaths()
