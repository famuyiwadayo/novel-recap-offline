// NovelJobCard.tsx
//
// One card per novel (group). Shows the discovery task's live status line,
// aggregate stats as small badges, and an expandable list of chapter
// tasks sorted by their intended reading order — chapter_fetch tasks
// don't carry chapter number/title as structured fields on Task
// (only `message`/`result` do, and only once populated), but `priority`
// was set to `chapter_priority_base + index` at spawn time in
// task_plugins.py, so it doubles as a reliable sort key here.

import { useMemo, useState } from "react";
import type { TaskStats, Task } from "@/types";
import { api } from "@/api/task-manager";

const STATE_STYLES: Record<
    Task["state"],
    { dot: string; text: string; bar: string; label: string }
> = {
    QUEUED: { dot: "bg-slate-500", text: "text-slate-400", bar: "bg-slate-500", label: "Queued" },
    RUNNING: { dot: "bg-sky-400", text: "text-sky-300", bar: "bg-sky-400", label: "Running" },
    RETRYING: { dot: "bg-amber-400", text: "text-amber-300", bar: "bg-amber-400", label: "Retrying" },
    PAUSED: { dot: "bg-violet-400", text: "text-violet-300", bar: "bg-violet-400", label: "Paused" },
    SUCCESS: { dot: "bg-emerald-400", text: "text-emerald-300", bar: "bg-emerald-400", label: "Done" },
    DEAD: { dot: "bg-rose-500", text: "text-rose-400", bar: "bg-rose-500", label: "Failed" },
    CANCELLED: { dot: "bg-slate-600", text: "text-slate-500", bar: "bg-slate-600", label: "Cancelled" },
};

function StatusDot({ state }: { state: Task["state"] }) {
    const s = STATE_STYLES[state];
    return (
        <span className="relative flex h-2 w-2 shrink-0">
            {state === "RUNNING" && (
                <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${s.dot} opacity-60 motion-reduce:animate-none`} />
            )}
            <span className={`relative inline-flex h-2 w-2 rounded-full ${s.dot}`} />
        </span>
    );
}

function ProgressBar({ task }: { task: Task }) {
    const s = STATE_STYLES[task.state];
    const pct = Math.round(task.progress * 100);
    return (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
            <div
                className={`h-full rounded-full ${s.bar} transition-[width] duration-300 ease-out ${task.state === "RUNNING" ? "animate-pulse motion-reduce:animate-none" : ""
                    }`}
                style={{ width: `${pct}%` }}
            />
        </div>
    );
}

function StatBadge({ label, value, tone }: { label: string; value: number; tone: string }) {
    if (value === 0) return null;
    return (
        <span className={`inline-flex items-center gap-1 rounded-full bg-slate-800/80 px-2 py-0.5 text-xs font-medium ${tone}`}>
            <span className="tabular-nums">{value}</span>
            <span className="text-slate-500">{label}</span>
        </span>
    );
}

type NovelJobCardProps = {
    group: string;
    discoveryTask: Task | undefined;
    chapterTasks: Task[];
    stats: TaskStats | undefined;
};

export function NovelJobCard({ group, discoveryTask, chapterTasks, stats }: NovelJobCardProps) {
    const [expanded, setExpanded] = useState(false);
    const [busy, setBusy] = useState(false);

    const sortedChapters = useMemo(
        () => [...chapterTasks].sort((a, b) => a.priority - b.priority),
        [chapterTasks]
    );

    const novelTitle =
        discoveryTask?.state === "SUCCESS" && discoveryTask.result
            ? (discoveryTask.result as { title?: string }).title
            : undefined;

    const isJobPaused = (stats?.paused ?? 0) > 0 && (stats?.running ?? 0) === 0 && (stats?.queued ?? 0) === 0;
    const hasDead = (stats?.dead ?? 0) > 0;

    async function withBusy(fn: () => Promise<unknown>) {
        setBusy(true);
        try {
            await fn();
        } finally {
            setBusy(false);
        }
    }

    return (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm shadow-black/20">
            {/* header row: title / novel id, action buttons */}
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-slate-100">
                        {novelTitle ?? `Novel #${group}`}
                    </h3>
                    {novelTitle && <p className="text-xs text-slate-500">#{group}</p>}
                </div>

                <div className="flex shrink-0 items-center gap-1.5">
                    {hasDead && (
                        <button
                            type="button"
                            disabled={busy}
                            onClick={() => withBusy(() => api.retryFailed(group))}
                            className="rounded-md bg-rose-500/10 px-2 py-1 text-xs font-medium text-rose-300 ring-1 ring-inset ring-rose-500/30 transition hover:bg-rose-500/20 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
                        >
                            Retry failed ({stats?.dead})
                        </button>
                    )}
                    <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                            withBusy(() => (isJobPaused ? api.resumeJob(group) : api.pauseJob(group)))
                        }
                        className="rounded-md bg-slate-800 px-2 py-1 text-xs font-medium text-slate-300 transition hover:bg-slate-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
                    >
                        {isJobPaused ? "Resume" : "Pause"}
                    </button>
                    <button
                        type="button"
                        disabled={busy}
                        onClick={() => withBusy(() => api.cancelJob(group))}
                        className="rounded-md bg-slate-800 px-2 py-1 text-xs font-medium text-slate-400 transition hover:bg-rose-500/20 hover:text-rose-300 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
                        aria-label="Cancel this job"
                    >
                        Cancel
                    </button>
                </div>
            </div>

            {/* discovery status line */}
            {discoveryTask && discoveryTask.state !== "SUCCESS" && (
                <div className="mt-3 space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                        <span className={`flex items-center gap-1.5 ${STATE_STYLES[discoveryTask.state].text}`}>
                            <StatusDot state={discoveryTask.state} />
                            {discoveryTask.message || STATE_STYLES[discoveryTask.state].label}
                        </span>
                        <span className="tabular-nums text-slate-500">
                            {Math.round(discoveryTask.progress * 100)}%
                        </span>
                    </div>
                    <ProgressBar task={discoveryTask} />
                    {discoveryTask.error && (
                        <p className="text-xs text-rose-400">{discoveryTask.error}</p>
                    )}
                </div>
            )}

            {/* chapter stats summary */}
            {stats && stats.total > 1 && (
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                    <StatBadge label="queued" value={stats.queued} tone="text-slate-400" />
                    <StatBadge label="running" value={stats.running} tone="text-sky-300" />
                    <StatBadge label="retrying" value={stats.retrying} tone="text-amber-300" />
                    <StatBadge label="paused" value={stats.paused} tone="text-violet-300" />
                    <StatBadge label="done" value={stats.success} tone="text-emerald-300" />
                    <StatBadge label="failed" value={stats.dead} tone="text-rose-400" />
                    <StatBadge label="cancelled" value={stats.cancelled} tone="text-slate-500" />

                    {sortedChapters.length > 0 && (
                        <button
                            type="button"
                            onClick={() => setExpanded((e) => !e)}
                            className="ml-auto text-xs font-medium text-teal-400 transition hover:text-teal-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 rounded"
                        >
                            {expanded ? "Hide chapters" : `Show ${sortedChapters.length} chapters`}
                        </button>
                    )}
                </div>
            )}

            {/* expandable chapter list */}
            {expanded && (
                <ul className="mt-3 max-h-72 space-y-1 overflow-y-auto rounded-lg border border-slate-800/80 bg-slate-950/40 p-1.5">
                    {sortedChapters.map((t) => {
                        const s = STATE_STYLES[t.state];
                        const resultTitle = (t.result as { title?: string } | undefined)?.title;
                        return (
                            <li
                                key={t.id}
                                className="flex items-center gap-2 rounded-md px-2 py-1 text-xs hover:bg-slate-800/60"
                            >
                                <StatusDot state={t.state} />
                                <span className={`min-w-0 flex-1 truncate ${s.text}`}>
                                    {resultTitle ?? t.message ?? s.label}
                                </span>
                                {t.state === "RUNNING" && (
                                    <span className="tabular-nums text-slate-500">{Math.round(t.progress * 100)}%</span>
                                )}
                                {t.state === "DEAD" && (
                                    <button
                                        type="button"
                                        onClick={() => api.retryTask(t.id)}
                                        className="rounded px-1.5 py-0.5 text-[11px] font-medium text-rose-300 ring-1 ring-inset ring-rose-500/30 hover:bg-rose-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
                                    >
                                        Retry
                                    </button>
                                )}
                            </li>
                        );
                    })}
                </ul>
            )}
        </div>
    );
}