// useTaskEvents.ts
//
// Correct pattern for subscribing to high-frequency Tauri events without
// tanking render performance. Two things this gets right that are easy to
// get wrong:
//
// 1. Cleanup: listen() returns a Promise<UnlistenFn>. If the effect doesn't
//    await it and call it on unmount, every remount (React 18 StrictMode
//    double-invokes effects in dev!) leaves a duplicate listener running
//    forever — each firing on every future event. This alone can make an
//    app get progressively slower the longer it's open / the more it
//    navigates, which matches "the console became very slow" over time.
//
// 2. Batching: a burst of events (e.g. several chapters progressing at
//    once) shouldn't cause a burst of synchronous re-renders. Events are
//    buffered in a ref and flushed once per animation frame instead of
//    once per event.

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { Event, listen } from "@tauri-apps/api/event";
import { Task, TaskKind, TaskStats } from "@/types";

// A single kind ("chapter_fetch"), multiple kinds (["chapter_fetch", "image_download"]),
// or a full predicate for anything more specific (e.g. kind + group together).
type TaskFilter = TaskKind | TaskKind[] | ((task: Task) => boolean);

function matchesFilter(task: Task, filter?: TaskFilter): boolean {
  if (!filter) return true;
  if (typeof filter === "function") return filter(task);
  if (typeof filter === "string") return task.kind === filter;
  return filter.includes(task.kind);
}

export function useTaskEvents(filter?: TaskFilter) {
  const [tasks, setTasks] = useState<Map<string, Task>>(new Map());
  const [statsByGroup, setStatsByGroup] = useState<Map<string, TaskStats>>(new Map());

  // events land here as fast as they arrive; React state only updates once
  // per animation frame, not once per event
  const pendingTasks = useRef<Map<string, Task>>(new Map());
  const pendingStats = useRef<Map<string, TaskStats>>(new Map());
  const rafId = useRef<number | null>(null);

  // Filtering happens at ingestion (inside the event callback below), so a
  // component that only cares about "image_download" never even stores
  // "chapter_fetch" updates — no unrelated re-renders. The filter is read
  // from a ref (always current) rather than captured directly, so passing
  // a fresh inline array/function every render does NOT tear down and
  // re-register the listener — only the effect's own stable deps do that.
  const filterRef = useRef<TaskFilter | undefined>(filter);
  filterRef.current = filter;

  const scheduleFlush = useCallback(() => {
    if (rafId.current !== null) return; // already scheduled — coalesce
    rafId.current = requestAnimationFrame(() => {
      rafId.current = null;
      if (pendingTasks.current.size > 0) {
        setTasks((prev) => {
          const next = new Map(prev);
          for (const [id, t] of pendingTasks.current) next.set(id, t);
          return next;
        });
        pendingTasks.current.clear();
      }
      if (pendingStats.current.size > 0) {
        setStatsByGroup((prev) => {
          const next = new Map(prev);
          for (const [group, s] of pendingStats.current) next.set(group, s);
          return next;
        });
        pendingStats.current.clear();
      }
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    let unlistenTask: (() => void) | undefined;
    let unlistenStats: (() => void) | undefined;

    listen<Task>("task-update", (event) => {
      if (!matchesFilter(event.payload, filterRef.current)) return;

      pendingTasks.current.set(event.payload.id, event.payload);
      scheduleFlush();
    }).then((fn) => {
      if (cancelled)
        fn(); // effect already cleaned up before this resolved — undo immediately
      else unlistenTask = fn;
    });

    listen<TaskStats>("queue-stats", (event) => {
      pendingStats.current.set(event.payload.group ?? "__global__", event.payload);
      scheduleFlush();
    }).then((fn) => {
      if (cancelled) fn();
      else unlistenStats = fn;
    });

    return () => {
      cancelled = true;
      unlistenTask?.();
      unlistenStats?.();
      if (rafId.current !== null) {
        cancelAnimationFrame(rafId.current);
        rafId.current = null;
      }
    };
  }, [scheduleFlush]);

  return { tasks, statsByGroup };
}

// --- Option B: filter a Map you already have (e.g. from ONE shared/top- ---
// --- level useTaskEvents() call, with multiple child components each    ---
// --- deriving their own filtered slice) instead of subscribing per      ---
// --- component. Simpler, and correctly reflects tasks that arrived      ---
// --- before you started filtering for them — trades that off against    ---
// --- every consumer recomputing on any task update, not just relevant   ---
// --- ones. Fine unless you have a large number of differently-filtered  ---
// --- views simultaneously.

export function useTasksByKind(tasks: Map<string, Task>, kinds: TaskKind | TaskKind[]): Task[] {
  const kindKey = Array.isArray(kinds) ? kinds.join(",") : kinds; // stable dep even for inline arrays
  return useMemo(() => {
    const kindSet = new Set(Array.isArray(kinds) ? kinds : [kinds]);
    return [...tasks.values()].filter((t) => kindSet.has(t.kind));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks, kindKey]);
}

// Usage — pair with a memoized row component so updating one task's
// progress doesn't re-render every other row in the list:
//
// const TaskRow = React.memo(function TaskRow({ task }: { task: TaskUpdate }) {
//   return <div>{task.message} — {Math.round(task.progress * 100)}%</div>;
// });
//
//   // Option A — subscribe once per component, filtered at the source:
//   function ChapterList({ group }: { group: string }) {
//     const { tasks } = useTaskEvents((t) => t.kind === "chapter_fetch" && t.group === group);
//     return <>{[...tasks.values()].map((t) => <TaskRow key={t.id} task={t} />)}</>;
//   }
//
//   function DownloadsPanel() {
//     const { tasks } = useTaskEvents(["chapter_fetch", "image_download"]);
//     return <>{[...tasks.values()].map((t) => <TaskRow key={t.id} task={t} />)}</>;
//   }
//
//   // Option B — one shared subscription (e.g. in a top-level provider),
//   // multiple components deriving filtered slices from the same Map:
//   function AppShell() {
//     const { tasks, statsByGroup } = useTaskEvents(); // no filter — tracks everything
//     return (
//       <TaskContext.Provider value={{ tasks, statsByGroup }}>
//         <ChapterListB group="42" />
//         <ImageDownloadsPanel />
//       </TaskContext.Provider>
//     );
//   }
//   function ChapterListB({ group }: { group: string }) {
//     const { tasks } = useContext(TaskContext);
//     const chapters = useTasksByKind(tasks, "chapter_fetch")
//       .filter((t) => t.group === group);
//     return <>{chapters.map((t) => <TaskRow key={t.id} task={t} />)}</>;
//   }
//   function ImageDownloadsPanel() {
//     const { tasks } = useContext(TaskContext);
//     const images = useTasksByKind(tasks, "image_download");
//     return <>{images.map((t) => <TaskRow key={t.id} task={t} />)}</>;
//   }
