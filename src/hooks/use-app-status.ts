// useAppStatus.ts
//
// Small, focused hooks for app-wide status that isn't per-task: whether
// the backend is online, and whether the queue is globally paused. Kept
// separate from useTaskEvents.ts on purpose — that hook is scoped to
// task/stats events only, per its own docstring.
//
// Both hooks follow the same shape: fetch the CURRENT value once on
// mount, THEN subscribe for live updates — events only fire on changes,
// not on demand, so a component mounting after the app's been running
// for a while (or a second window) needs an explicit initial fetch
// rather than waiting indefinitely for the next transition.

import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { api } from "@/api/task-manager";
import type { Connectivity, QueuePaused } from "@/api/task-manager";

export function useConnectivity(): boolean {
  const [online, setOnline] = useState(true); // optimistic until the initial fetch resolves

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;

    api.getConnectivity().then((c) => {
      if (!cancelled) setOnline(c.online);
    });

    listen<Connectivity>("connectivity", (event) => {
      setOnline(event.payload.online);
    }).then((fn) => {
      if (cancelled) fn();
      else unlisten = fn;
    });

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  return online;
}

/** Returns [paused, loaded] — `loaded` lets callers avoid flashing a
 * wrong button label before the initial fetch resolves. */
export function useQueuePaused(): [boolean, boolean] {
  const [paused, setPaused] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;

    api.getQueuePaused().then((s) => {
      if (!cancelled) {
        setPaused(s.paused);
        setLoaded(true);
      }
    });

    listen<QueuePaused>("queue-paused", (event) => {
      setPaused(event.payload.paused);
    }).then((fn) => {
      if (cancelled) fn();
      else unlisten = fn;
    });

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  return [paused, loaded];
}
