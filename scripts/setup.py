#!/usr/bin/env python3
"""
scripts/setup.py

One-time (or "run again after pulling changes") setup: installs Python
dependencies, then installs the Playwright Chromium headless shell to the
EXACT path main.py's dev-mode resolve_browser_path() expects
(src-tauri/binaries/ms-playwright) — not Playwright's default OS cache
dir, since the app reads PLAYWRIGHT_BROWSERS_PATH explicitly and won't
find browsers anywhere else.

This only handles the Python side. The Rust-side build.rs step that
copies src-tauri/binaries/ms-playwright into target/debug still runs
automatically as part of `cargo build` / `tauri dev` — nothing to do here
for that part.

Usage:
    python scripts/setup.py
    python scripts/setup.py --skip-browser   # if you've already installed it
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = (
    SCRIPT_DIR.parent
)  # adjust if scripts/ isn't directly under the project root
PYTHON_SRC_DIR = PROJECT_ROOT / "src-tauri" / "src-python"
BROWSERS_PATH = PROJECT_ROOT / "src-tauri" / "binaries" / "ms-playwright"


def run(cmd: list[str], **kwargs) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def install_python_deps() -> None:
    print("\n== Installing Python dependencies ==")
    if shutil.which("uv") and (PYTHON_SRC_DIR / "pyproject.toml").exists():
        run(["uv", "sync"], cwd=PYTHON_SRC_DIR)
        return
    if (PYTHON_SRC_DIR / "pyproject.toml").exists():
        run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=PYTHON_SRC_DIR)
        return
    requirements = PYTHON_SRC_DIR / "requirements.txt"
    if requirements.exists():
        run([sys.executable, "-m", "pip", "install", "-r", str(requirements)])
        return
    print(
        "! No pyproject.toml or requirements.txt found under src-python/ — "
        "skipping dependency install. Adjust this script to match your actual "
        "project layout if this isn't right."
    )


def install_playwright_browser() -> None:
    print(f"\n== Installing Playwright Chromium headless shell ==")
    print(f"Target: {BROWSERS_PATH}")
    BROWSERS_PATH.mkdir(parents=True, exist_ok=True)

    env = {"PLAYWRIGHT_BROWSERS_PATH": str(BROWSERS_PATH)}
    import os

    full_env = {**os.environ, **env}

    # --only-shell keeps this to the headless-only Chromium build rather
    # than the full browser + Firefox + WebKit + ffmpeg a bare
    # `playwright install` would pull — see README's "Playwright browser
    # bundling" section for why this matters for bundle size.
    run(
        [sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"],
        env=full_env,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="Skip installing the Playwright browser (e.g. already installed).",
    )
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="Skip installing Python dependencies.",
    )
    args = parser.parse_args()

    if not args.skip_deps:
        install_python_deps()
    if not args.skip_browser:
        install_playwright_browser()

    print("\n== Setup complete ==")
    print(f"PLAYWRIGHT_BROWSERS_PATH for dev mode: {BROWSERS_PATH}")
    print("If PYTHON_SRC_DIR/BROWSERS_PATH above don't match your actual project")
    print("layout, adjust the constants at the top of this script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
