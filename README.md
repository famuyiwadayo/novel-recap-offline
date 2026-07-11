# Novel Scraper — Architecture

An offline-first desktop app (Tauri + pytauri + Python) that scrapes novel
sites for metadata and chapter content, using a headless-browser-backed
scraper registry and a priority task queue for concurrent, resumable
downloads.

## How the pieces fit together

```
┌─────────────────────────────────────────────────────────────────┐
│ Frontend (TS/JS)                                                 │
│   pyInvoke("scrape_novel", {...})  ──────┐   listen("task-update")│
└───────────────────────────────────────────┼──────────────────────┘
                                             │        ▲
                                    IPC (pyInvoke)     │ Tauri events
                                             ▼        │
┌─────────────────────────────────────────────────────────────────┐
│ backend/commands.py  — the only IPC surface                      │
│   scrape_novel, download_image, retry_*, pause_*, cancel_*, ...  │
└───────────────────────────┬───────────────────────────────────────┘
                             │ calls into
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ backend/app.py  — singletons + lifecycle                          │
│   manager (TaskQueueManager) · pw_manager · network_mgr           │
│   wire_events() · startup() · shutdown()                          │
└───────┬─────────────────────┬──────────────────────┬──────────────┘
        │                     │                      │
        ▼                     ▼                      ▼
┌───────────────┐   ┌───────────────────┐   ┌─────────────────────┐
│ managers/      │   │ managers/          │   │ scrapers/            │
│ task_queue.py  │   │ network_manager.py │   │ registry.py, base.py,│
│                │   │ playwright_manager │   │ vendors/,            │
│ priority queue,│──▶│                    │◀──│ task_plugins.py      │
│ retry/backoff, │   │ owns the browser,  │   │                      │
│ pause/cancel,  │   │ connectivity check │   │ resolves + calls the │
│ plugin dispatch│   │ (wait_until_online)│   │ right vendor scraper │
└───────────────┘   └───────────────────┘   └─────────────────────┘
```

Dependency direction is one-way: `commands.py → app.py → managers/ & scrapers/`.
Nothing in `managers/`/`scrapers/` imports back up toward `commands.py` or
`app.py` — no circular imports anywhere in the graph.

## Directory layout

```
src-python/
  main.py                        # entry point — builds the Tauri app, wires everything, runs it
  backend/
    app.py                       # singleton construction (manager/pw_manager/network_mgr),
                                  # wire_events()/startup()/shutdown() — NO commands live here
    commands.py                  # every @commands.command() — the IPC surface, thin wrappers
    schemas.py                   # Pydantic models that cross the IPC boundary + conversion fns
    plugins.py                   # ImageDownloadPlugin (generic, not scraper-specific)
    shutdown_listener.py         # bridges window-close into the async runtime → shutdown()

    managers/
      task_queue.py              # generic priority task queue engine (see below)
      playwright_manager.py      # one shared browser, pooled/bounded contexts
      network_manager.py         # wraps playwright_manager; owns connectivity polling

    scrapers/
      base.py                    # BaseScraper, NovelMetadata, ExtractedChapter
      registry.py                # ScraperRegistry — resolves a URL to a vendor scraper
      vendors/                   # one file per site, each a BaseScraper subclass
      task_plugins.py            # bridges registry.py into task_queue.py's Plugin interface

src-tauri/
  binaries/ms-playwright/        # bundled Chromium headless shell (see "Playwright" below)
  build.rs                       # (your addition) copies binaries/ms-playwright into
                                  # target/debug at build time — see "Playwright" below
```

## Core components

### TaskQueueManager (`managers/task_queue.py`)

A generic, domain-agnostic priority queue. Doesn't know novels or images
exist — it dispatches `Task`s to registered `Plugin`s by `kind` string.

- **Priority**: lower `priority` value runs first, stable FIFO within a tier.
- **Retry**: exponential backoff (`retry_base_delay` × 2^retries, capped at
  `retry_max_delay`), dead-lettering into `DEAD` once `max_retries` is
  exhausted (visible, not silently dropped).
- **Dynamic spawning**: a plugin's `PluginResult.spawn` lets it enqueue
  child tasks — this is how "discover a novel" fans out into N "fetch
  chapter" tasks without a bespoke two-phase state machine.
- **Pause/resume/cancel, at three scopes**: global (`pause()`/`resume()`),
  per-job (`pause_group()`/`resume_group()`/`cancel_group()`), and
  per-task (`pause_task()`/`resume_task()`/`cancel()`). Pausing a
  currently-running task by default lets it finish naturally and only
  holds its *next* attempt; `cancel_running=True` stops it immediately
  instead.
- **Grouping**: tasks share a `group` (e.g. `str(novel_id)`) so an entire
  job's progress/retry/pause can be scoped together.

### PlaywrightManager (`managers/playwright_manager.py`)

One Chromium instance for the app's entire lifetime — launching a browser
per task would defeat the point of a concurrent queue. Hands out
**contexts** (isolated sessions) from a semaphore-bounded, reused pool via
`acquire_context()`/`release_context()`. Cleanup is cancellation-safe: if a
task using a context gets cancelled mid-flight, the context's slot is
still released via a shielded `CancelScope` rather than leaking.

### NetworkManager (`managers/network_manager.py`)

The single network access point scrapers use — wraps `PlaywrightManager`
directly. Exposes `page(url)` (a live, navigated `Page` for scrapers doing
selectors/waiting) and lightweight `raw_get()`. Also owns **connectivity
awareness**, since this app runs mostly offline:

- Polls connectivity via a cheap raw TCP probe (not a browser navigation)
  — fast while offline (to notice recovery quickly), slower while online.
- `wait_until_online()` blocks gracefully rather than failing outright —
  a fetch that starts right as connectivity drops just waits.
- `on_connectivity_change(cb)` notifies subscribers on every transition.
  `app.py`'s `wire_events()` wires this to `manager.pause()`/`resume()` +
  `manager.requeue_failed()` on reconnect, so a job doesn't just sit
  DEAD after an outage — it recovers automatically.

### Scraper registry (`scrapers/registry.py`, `scrapers/base.py`, `scrapers/vendors/`)

`BaseScraper` subclasses live one-per-site under `vendors/`, each
implementing `can_handle(url)` (instance method — the registry holds
instantiated scrapers, not classes) plus `async parse_metadata(source_url,
network_mgr)` and `async parse_chapter(novel_id, chapter_url, chapter_num,
network_mgr)`. `ScraperRegistry` resolves a URL to the right instance.

### task_plugins.py — the registry ↔ task_queue bridge

`RegistryNovelDiscoveryPlugin`/`RegistryChapterFetchPlugin` are the two
`Plugin`s registered with `TaskQueueManager`. They don't know about any
specific vendor — they resolve the right scraper via the registry and
call it, auto-dispatching whether the scraper's methods are sync or async
under the hood. This is what lets `requests`-based and Playwright-based
scrapers coexist in the same vendor folder with zero special-casing.

## Request flow: scraping a novel end-to-end

1. Frontend calls `pyInvoke("scrape_novel", { novelId, sourceUrl })`.
2. `commands.py::scrape_novel` enqueues a `novel_discovery` task
   (`priority=-10`, so discovery jumps ahead of other queued work) with
   `group=str(novel_id)`.
3. A worker picks it up; `RegistryNovelDiscoveryPlugin` resolves the
   scraper via the registry, calls `scraper.parse_metadata(url, network_mgr)`
   (which internally does `async with network_mgr.page(url) as page: ...`).
4. The plugin spawns one `chapter_fetch` task per chapter URL, priority
   matching reading order, same `group`.
5. Workers pull those concurrently (bounded by `num_workers` and by
   `PlaywrightManager`'s `max_contexts`); `RegistryChapterFetchPlugin`
   resolves + calls `scraper.parse_chapter(...)`, persists the result.
6. Every state transition emits a `task-update` event; aggregate counts
   emit `queue-stats`. The frontend renders progress from these, filtered
   by `group`.
7. If a chapter fails, it retries with backoff up to `max_retries`, then
   goes `DEAD` (visible in stats, not silently lost). `retry_failed(group)`
   or `retry_task(id)` bring it back manually; a reconnect after an outage
   brings it back automatically.

## pytauri / async model essentials

- pytauri runs its Python-side async runtime on **anyio's asyncio
  backend** specifically (confirmed via `start_blocking_portal("asyncio")`
  in `main.py`) — this is why Playwright's **async API** is the right
  choice for scrapers here, not the sync API (which can't run inside an
  already-active asyncio loop).
- **Startup is NOT lazy/per-command.** `main.py` calls `wire_events()`
  (sync), then `portal.call(startup)` — which **blocks** until the browser
  is actually launched, before the app starts accepting IPC calls — then
  fire-and-forgets the two infinite loops (`manager.start`,
  `network_mgr.start_monitoring`) via `portal.start_task_soon()`. Commands
  never need to check "has the manager started yet" — `enqueue()` is safe
  to call even before workers exist (tasks just sit `QUEUED`).
- **Sync ↔ async boundary**: anything called from a Tauri-side synchronous
  callback (window events, menu events) has to cross into the anyio loop
  via `AsyncTools.to_sync` — see `shutdown_listener.py`.

## Playwright browser bundling

This app is offline-first, so the browser can't be downloaded at runtime —
it has to ship with the app. Key points from the current `main.py`:

- **`PLAYWRIGHT_BROWSERS_PATH`** must be set *before* anything touches
  Playwright (before `PlaywrightManager.start()` runs), since Playwright's
  driver reads it once at launch. `main.py`'s `setup` hook
  (`app_setup_hook()`, passed to `builder_factory().build(setup=...)`)
  sets this as early as possible, resolved differently per environment:
  - **Dev**: points straight at the source tree's
    `binaries/ms-playwright`, bypassing `target/debug` — Cargo doesn't
    auto-copy arbitrary resource folders there for you in dev mode.
  - **Packaged/frozen**: resolved via `Manager.path(app_handle).resource_dir()`
    joined with `binaries/ms-playwright` — the extracted installer's
    bundled-resources location.
- **Browsers live at `src-tauri/binaries/ms-playwright`** in this project
  — install them there explicitly (see the setup script below), don't
  rely on Playwright's default OS cache dir, or the packaged app won't
  find them.
- **A `build.rs` step copies `binaries/ms-playwright` into `target/debug`**
  during `cargo build`/`tauri dev` — this is necessary because, again,
  Tauri's resource-bundling mechanism (`tauri.conf.json`'s
  `bundle.resources`) only applies to production `tauri build`, not dev
  runs.
- **Only install what you need**: `playwright install --only-shell
  chromium` gets you the headless shell (much smaller than the full
  Chromium + Firefox + WebKit + ffmpeg that a bare `playwright install`
  pulls) — see the setup script.

## Setup

Run `python scripts/setup.py` from the project root before first `tauri dev`
— see that script for what it does (installs Python deps, installs the
Chromium headless shell to the exact path the app expects in dev mode).
The Rust-side `build.rs` copy step still runs automatically as part of
`cargo build`/`tauri dev`; the setup script only handles the Python side.

## Known gaps — worth reconciling

The real `main.py` you shared revealed a few places where the
already-built files (from earlier in this project) and your current code
have drifted apart. Flagging rather than silently papering over:

1. **`ScraperRegistry` method name**: your real code calls
   `scraper_registry.get_scraper_for_url(url)`, but `task_plugins.py`'s
   `RegistryLike` protocol currently assumes `.resolve(url)`. One-line fix
   in `task_plugins.py` once confirmed.
2. **`NetworkManager`'s constructor**: your `main.py` snippet shows
   `NetworkManager(app_handle_)` (and even re-constructs a new instance
   inside `import_novel` rather than reusing the module-level singleton),
   but the `network_manager.py` built earlier takes a `PlaywrightManager`
   instead. Worth deciding which shape is canonical — happy to reconcile
   once you confirm.
3. **Shutdown hook mechanism**: your `main.py` passes an `on_event`
   callback to `app.run_return(on_event)`, which receives `RunEventType`
   (commented-out `RunEvent.Ready` case suggests this is the intended
   place for lifecycle hooks) — this is likely the more idiomatic
   mechanism for shutdown than `shutdown_listener.py`'s
   `Listener.once(app_handle, "tauri://close-requested", ...)` approach,
   which was a best-guess without a confirmed API reference at the time.
   Worth switching to `on_event` handling `RunEventType`'s exit/close
   variant once you confirm its exact shape.
4. **`import_novel` vs `scrape_novel`**: your snippet shows a synchronous
   `import_novel` command that calls `scraper.parse_metadata()` directly
   and returns `NovelMetadata` inline — no task queue involved. This might
   be intentional as a lightweight "preview metadata before committing to
   a full download" step, separate from the queued `scrape_novel` flow
   that fans out into chapter downloads. Worth confirming that's the
   intended split rather than a leftover from before the queue existed.