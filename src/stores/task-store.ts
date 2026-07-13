// taskStore.ts
//
// ONE global subscription to task-update/queue-stats/connectivity/
// queue-paused events, instead of useTaskEvents.ts's per-component
// listen() calls. Now that there's a Library route, a Downloads route,
// and a Novel detail route that all potentially want live task data
// simultaneously, a shared external store beats re-subscribing in each —
// no provider tree needed (Zustand stores are plain singletons), and
// components only re-render for the specific slice they select.
//
// Same RAF-batching discipline as useTaskEvents.ts (a burst of events
// shouldn't cause a burst of synchronous re-renders) — replicated here
// since Zustand's `set()` calls subscribers just like React state would.
//
// Auto-initializes on first import (see the bottom of this file) — no
// explicit wiring needed in main.tsx. Safe to import this module from
// anywhere; the actual listen() calls only ever get registered once.

import { create } from "zustand";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { api } from "@/api/task-manager";
import type { Connectivity, QueuePaused } from "@/api/task-manager";
import type { Task, TaskStats } from "@/types";
import { queryClient } from "@/query-client";
import { queryKeys } from "@/queries";

type TaskStoreState = {
  tasks: Map<string, Task>;
  statsByGroup: Map<string, TaskStats>;
  online: boolean;
  queuePaused: boolean;
  /** true once the initial connectivity/queue-paused fetch has resolved —
   * events only fire on CHANGES, so a store created after the app's been
   * running a while needs an explicit fetch for where things stand now. */
  ready: boolean;
};

type TaskStore = TaskStoreState & {
  /** Idempotent — safe to call more than once (e.g. React StrictMode's
   * double-invoke in dev); only the first call actually does anything.
   * Returns a cleanup function, mainly useful for tests/hot-reload. */
  init: () => () => void;
};

let pendingTasks = new Map<string, Task>();
let pendingStats = new Map<string, TaskStats>();
let rafId: number | null = null;
let initialized = false;

export const useTaskStore = create<TaskStore>((set, get) => ({
  tasks: new Map(),
  statsByGroup: new Map(),
  online: true,
  queuePaused: false,
  ready: false,

  init: () => {
    if (initialized) return () => {};
    initialized = true;

    let cancelled = false;
    const unlistenFns: UnlistenFn[] = [];
    const track = (p: Promise<UnlistenFn>) => {
      p.then((fn) => (cancelled ? fn() : unlistenFns.push(fn)));
    };

    function scheduleFlush() {
      if (rafId !== null) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        if (pendingTasks.size > 0) {
          const next = new Map(get().tasks);
          for (const [id, t] of pendingTasks) next.set(id, t);
          pendingTasks = new Map();
          set({ tasks: next });
        }
        if (pendingStats.size > 0) {
          const next = new Map(get().statsByGroup);
          for (const [g, s] of pendingStats) next.set(g, s);
          pendingStats = new Map();
          set({ statsByGroup: next });
        }
      });
    }

    track(
      listen<Task>("task-update", (e) => {
        pendingTasks.set(e.payload.id, e.payload);
        scheduleFlush();

        // Bridge into TanStack Query: a terminal state means persisted
        // data (SQLite, via app.py's _on_task_persist) just changed —
        // invalidate immediately rather than waiting on the RAF-batched
        // visual flush above, since invalidateQueries is cheap/idempotent
        // and this is what replaces manually refetching on a
        // "terminalSignature" dependency in each consuming component.
        const isTerminal = e.payload.state === "SUCCESS" || e.payload.state === "DEAD";
        if (isTerminal && e.payload.group) {
          const novelId = Number(e.payload.group);
          if (e.payload.kind === "novel_discovery") {
            queryClient.invalidateQueries({ queryKey: queryKeys.novel(novelId) });
            queryClient.invalidateQueries({ queryKey: queryKeys.novels });
          } else if (e.payload.kind === "chapter_fetch") {
            queryClient.invalidateQueries({ queryKey: queryKeys.novelChapters(novelId) });
            queryClient.invalidateQueries({ queryKey: queryKeys.novels }); // downloaded_chapters count changed
          }
        }
      }),
    );
    track(
      listen<TaskStats>("queue-stats", (e) => {
        pendingStats.set(e.payload.group ?? "__global__", e.payload);
        scheduleFlush();
      }),
    );
    // connectivity/queue-paused are low-frequency — no batching needed
    track(listen<Connectivity>("connectivity", (e) => set({ online: e.payload.online })));
    track(listen<QueuePaused>("queue-paused", (e) => set({ queuePaused: e.payload.paused })));

    Promise.all([api.getConnectivity(), api.getQueuePaused()]).then(([conn, qp]) => {
      if (!cancelled) set({ online: conn.online, queuePaused: qp.paused, ready: true });
    });

    return () => {
      cancelled = true;
      initialized = false;
      for (const fn of unlistenFns) fn();
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
    };
  },
}));

// Auto-init on first import — a desktop Tauri app has no SSR/hydration
// concerns, so there's no reason to defer this behind a useEffect.
useTaskStore.getState().init();

// --- convenience selectors -------------------------------------------------
// Deliberately NOT pre-filtering into arrays here (e.g. a
// useTasksInGroup(group) returning Task[]) — that would allocate a new
// array on every store update regardless of relevance, causing
// consumers to re-render on unrelated changes. Components should derive
// filtered views via useMemo from the raw Maps below.

export function useTasks() {
  return useTaskStore((s) => s.tasks);
}
export function useStatsByGroup() {
  return useTaskStore((s) => s.statsByGroup);
}
export function useOnline() {
  return useTaskStore((s) => s.online);
}
export function useQueuePausedState() {
  return useTaskStore((s) => s.queuePaused);
}
