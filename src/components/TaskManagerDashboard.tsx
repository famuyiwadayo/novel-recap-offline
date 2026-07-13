// TaskManagerDashboard.tsx
//
// Top-level page: connectivity banner, form to start a new scrape, global
// pause/resume, and one NovelJobCard per group. Subscribes to task/stats
// events ONCE here via useTaskEvents() and passes filtered slices down —
// see the "Option B" pattern in useTaskEvents.ts for why (avoids each
// card re-subscribing independently).

import { useMemo, useState } from "react";
import { useTaskEvents, useConnectivity, useQueuePaused } from "@/hooks";
import { NovelJobCard } from "./NovelJobCard";
import { api } from "@/api/task-manager";

function ConnectivityBanner({ online }: { online: boolean }) {
    if (online) return null;
    return (
        <div
            role="status"
            aria-live="polite"
            className="flex items-center gap-2 border-b border-amber-500/20 bg-amber-500/10 px-4 py-2 text-sm text-amber-300"
        >
            <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60 motion-reduce:animate-none" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-400" />
            </span>
            Offline — active work is paused and will resume automatically once connectivity returns.
        </div>
    );
}

function NewScrapeForm({ onSubmitted }: { onSubmitted?: (novelId: number) => void }) {
    const [url, setUrl] = useState("https://wtr-lab.com/en/novel/53992/lord-god-tier-attribute-recruits-fallen-angels-of-original-sin");
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        if (!url.trim()) return;
        setSubmitting(true);
        setError(null);
        try {
            // novel_id no longer generated here — the backend's get_or_create_novel()
            // owns id assignment now (and reuses the existing row if this URL's
            // already in the library, instead of creating a duplicate entry)
            const novelId = await api.scrapeNovel(url.trim());
            setUrl("");
            onSubmitted?.(novelId);
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <form onSubmit={handleSubmit} className="flex flex-col gap-2 sm:flex-row sm:items-start">
            <div className="flex-1">
                <label htmlFor="novel-url" className="sr-only">
                    Novel page URL
                </label>
                <input
                    id="novel-url"
                    type="url"
                    required
                    defaultValue={url}
                    placeholder="https://wtr-lab.com/en/novel/..."
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 outline-none transition focus:border-teal-400 focus:ring-1 focus:ring-teal-400"
                />
                {error && <p className="mt-1 text-xs text-rose-400">{error}</p>}
            </div>
            <button
                type="submit"
                disabled={submitting || !url.trim()}
                className="shrink-0 rounded-lg bg-teal-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-teal-400 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
            >
                {submitting ? "Starting…" : "Start scraping"}
            </button>
        </form>
    );
}

function GlobalControls() {
    const [paused, loaded] = useQueuePaused();
    const [busy, setBusy] = useState(false);

    async function toggle() {
        setBusy(true);
        try {
            if (paused) {
                await api.resumeQueue();
            } else {
                await api.pauseQueue();
            }
            // no manual state flip here — the "queue-paused" event (already
            // subscribed inside useQueuePaused) updates real state once the
            // backend confirms it, so this always reflects the true source of
            // truth rather than an optimistic guess that could drift
        } finally {
            setBusy(false);
        }
    }

    return (
        <button
            type="button"
            onClick={toggle}
            disabled={busy || !loaded}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-300 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
        >
            {paused ? "Resume all" : "Pause all"}
        </button>
    );
}

export function TaskManagerDashboard() {
    const { tasks, statsByGroup } = useTaskEvents();
    const online = useConnectivity();

    const groups = useMemo(() => {
        const byGroup = new Map<string, { discovery?: (typeof tasksArr)[number]; chapters: typeof tasksArr }>();
        const tasksArr = [...tasks.values()];
        for (const t of tasksArr) {
            if (!t.group) continue;
            const entry = byGroup.get(t.group) ?? { discovery: undefined, chapters: [] };
            if (t.kind === "novel_discovery") entry.discovery = t;
            else if (t.kind === "chapter_fetch") entry.chapters.push(t);
            byGroup.set(t.group, entry);
        }
        // most recently started novel first — discovery tasks don't carry a
        // created-at timestamp on the wire, so this falls back to insertion
        // order via the Map, which useTaskEvents already preserves
        return [...byGroup.entries()].reverse();
    }, [tasks]);

    return (
        <div className="min-h-screen bg-slate-950 text-slate-100">
            <ConnectivityBanner online={online} />

            <header className="border-b border-slate-800 px-6 py-4">
                <div className="mx-auto flex max-w-3xl items-center justify-between gap-4">
                    <h1 className="text-lg font-semibold tracking-tight">Library downloads</h1>
                    <GlobalControls />
                </div>
            </header>

            <main className="mx-auto max-w-3xl px-6 py-6">
                <div className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
                    <NewScrapeForm />
                </div>

                {groups.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-slate-800 px-6 py-12 text-center">
                        <p className="text-sm text-slate-500">
                            Nothing here yet — paste a novel URL above to start a download.
                        </p>
                    </div>
                ) : (
                    <div className="space-y-3">
                        {groups.map(([group, { discovery, chapters }]) => (
                            <NovelJobCard
                                key={group}
                                group={group}
                                discoveryTask={discovery}
                                chapterTasks={chapters}
                                stats={statsByGroup.get(group)}
                            />
                        ))}
                    </div>
                )}
            </main>
        </div>
    );
}