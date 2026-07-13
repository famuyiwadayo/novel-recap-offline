// queryClient.ts
//
// Created at MODULE level, not inside a component — if it were created
// inside App(), a remount would wipe the entire cache. Both main.tsx
// (QueryClientProvider) and taskStore.ts (invalidation on live events)
// import this same instance.

import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Live updates arrive via taskStore's event-driven invalidation,
      // not polling — a generous staleTime avoids redundant refetches on
      // every component mount/window-focus for data that only actually
      // changes when a task-update event says so.
      staleTime: 30_000,
    },
  },
});
