// routes/downloads.tsx
//
// The "operations" view — active/recent jobs with full controls
// (pause/resume/cancel/retry, expandable chapter list). Adding new
// novels now lives on the Library page (/) instead of here, to avoid
// duplicating that flow across two routes.
//
// Reads from the shared taskStore instead of calling useTaskEvents()
// directly — same data, but now shared with the Library grid's live
// progress overlay rather than a separate subscription.

import { useMemo } from "react";
import { createFileRoute } from "@tanstack/react-router";
import type { Task } from "@/types";
import { useTasks, useStatsByGroup, useQueuePausedState } from "@/stores";
import { usePauseQueueMutation, useResumeQueueMutation } from "../queries";
import { NovelJobCard } from "@/components";

export const Route = createFileRoute("/downloads")({
    component: DownloadsPage,
});

function GlobalControls() {
    const paused = useQueuePausedState();
    const pauseQueue = usePauseQueueMutation();
    const resumeQueue = useResumeQueueMutation();
    const busy = pauseQueue.isPending || resumeQueue.isPending;

    return (
        <button
            type="button"
            onClick={() => (paused ? resumeQueue.mutate() : pauseQueue.mutate())}
            disabled={busy}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-300 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
        >
            {paused ? "Resume all" : "Pause all"}
        </button>
    );
}

function DownloadsPage() {
    const tasks = useTasks();
    const statsByGroup = useStatsByGroup();

    const groups = useMemo(() => {
        const byGroup = new Map<string, { discovery?: Task; chapters: Task[] }>();
        for (const t of tasks.values()) {
            if (!t.group) continue;
            const entry = byGroup.get(t.group) ?? { discovery: undefined, chapters: [] };
            if (t.kind === "novel_discovery") entry.discovery = t;
            else if (t.kind === "chapter_fetch") entry.chapters.push(t);
            byGroup.set(t.group, entry);
        }
        return [...byGroup.entries()].reverse(); // most recently started first
    }, [tasks]);

    return (
        <main className="mx-auto max-w-3xl px-6 py-6">
            <div className="mb-4 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-300">Active downloads</h2>
                <GlobalControls />
            </div>

            {groups.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-800 px-6 py-12 text-center">
                    <p className="text-sm text-slate-500">
                        Nothing in progress — add a novel from the Library page to start a download.
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
    );
}