// Novel detail page. Persisted metadata + downloaded chapters come from
// TanStack Query (backed by SQLite); in-progress task state (chapters not
// yet downloaded, retry controls) comes from the Zustand store, filtered
// to this novel's group.

import { useMemo } from "react";
import { createFileRoute } from "@tanstack/react-router";
import type { Task } from "@/types";
import { useTasks, useStatsByGroup } from "@/stores";
import { useNovelQuery, useNovelChaptersQuery, useRetryFailedMutation } from "@/queries";

export const Route = createFileRoute("/novel/$novelId")({
  component: NovelDetailPage,
});

const STATE_STYLES: Record<Task["state"], { dot: string; text: string }> = {
  QUEUED: { dot: "bg-slate-500", text: "text-slate-400" },
  RUNNING: { dot: "bg-sky-400", text: "text-sky-300" },
  RETRYING: { dot: "bg-amber-400", text: "text-amber-300" },
  PAUSED: { dot: "bg-violet-400", text: "text-violet-300" },
  SUCCESS: { dot: "bg-emerald-400", text: "text-emerald-300" },
  DEAD: { dot: "bg-rose-500", text: "text-rose-400" },
  CANCELLED: { dot: "bg-slate-600", text: "text-slate-500" },
};

function NovelDetailPage() {
  const { novelId } = Route.useParams();
  const novelIdNum = Number(novelId);
  const group = novelId; // group is str(novel_id) throughout the backend

  const { data: novel, isLoading: novelLoading } = useNovelQuery(novelIdNum);
  const { data: downloaded_chapters = [] } = useNovelChaptersQuery(novelIdNum);
  const retryFailed = useRetryFailedMutation();

  const tasks = useTasks();
  const statsByGroup = useStatsByGroup();
  const stats = statsByGroup.get(group);

  // live chapter_fetch tasks for this novel, sorted by priority (reading order)
  const liveChapterTasks = useMemo(
    () =>
      [...tasks.values()]
        .filter((t) => t.group === group && t.kind === "chapter_fetch")
        .sort((a, b) => a.priority - b.priority),
    [tasks, group]
  );

  const hasDead = (stats?.dead ?? 0) > 0;

  if (novelLoading) {
    return <main className="mx-auto max-w-3xl px-6 py-6 text-sm text-slate-500">Loading…</main>;
  }
  if (!novel) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-6 text-sm text-slate-500">
        Novel not found — it may have been removed from the library.
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-6">
      <div className="flex gap-5">
        <div className="w-32 shrink-0">
          {novel.cover_image_path || novel.cover_image_url ? (
            <img
              src={novel.cover_image_path ?? novel.cover_image_url ?? undefined}
              alt=""
              className="aspect-2/3 w-full rounded-lg object-cover shadow-lg shadow-black/40"
            />
          ) : (
            <div className="aspect-2/3 w-full rounded-lg bg-slate-800" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl text-left font-semibold text-slate-100">{novel.title ?? "Untitled"}</h1>
          <p className="mt-0.5 text-sm text-slate-400">
            {novel.author.filter(Boolean).join(", ") || "Unknown author"}
          </p>
          {novel.tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {novel.tags.map((t) => (
                <span key={t} className="rounded-full bg-slate-800 px-2 py-0.5 text-[11px] text-slate-400">
                  {t}
                </span>
              ))}
            </div>
          )}
          {novel.summary && <p className="mt-3 text-sm leading-relaxed text-slate-400">{novel.summary}</p>}

          <div className="mt-4 flex items-center gap-2">
            {hasDead && (
              <button
                type="button"
                disabled={retryFailed.isPending}
                onClick={() => retryFailed.mutate(group)}
                className="rounded-md bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-300 ring-1 ring-inset ring-rose-500/30 hover:bg-rose-500/20 disabled:opacity-50"
              >
                {retryFailed.isPending ? "Retrying…" : `Retry ${stats?.dead} failed`}
              </button>
            )}
            <span className="text-xs text-slate-500">
              {novel.downloaded_chapters}/{novel.total_chapters || "?"} chapters downloaded
            </span>
          </div>
        </div>
      </div>

      <h2 className="mb-2 mt-8 text-sm font-semibold text-slate-300">Chapters</h2>
      <ul className="divide-y divide-slate-800/80 rounded-lg border border-slate-800">
        {downloaded_chapters.map((c) => (
          <li key={c.chapter_number} className="flex items-center gap-2 px-3 py-2 text-sm">
            <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-400" />
            <span className="min-w-0 flex-1 truncate text-slate-200">
              {c.chapter_number}. {c.title ?? `Chapter ${c.chapter_number}`}
            </span>
          </li>
        ))}
        {liveChapterTasks
          .filter((t) => t.state !== "SUCCESS") // downloaded ones are already listed above
          .map((t) => {
            const s = STATE_STYLES[t.state];
            return (
              <li key={t.id} className="flex items-center gap-2 px-3 py-2 text-sm">
                <span className={`h-2 w-2 shrink-0 rounded-full ${s.dot}`} />
                <span className={`min-w-0 flex-1 truncate ${s.text}`}>{t.message || s.text}</span>
              </li>
            );
          })}
        {downloaded_chapters.length === 0 && liveChapterTasks.length === 0 && (
          <li className="px-3 py-6 text-center text-sm text-slate-500">
            No chapters yet — discovery may still be in progress.
          </li>
        )}
      </ul>
    </main>
  );
}