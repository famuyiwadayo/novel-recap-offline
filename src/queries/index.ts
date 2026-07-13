// queries.ts
//
// useQuery hooks for read commands, useMutation hooks for write/command
// ones. Command mutations (pause/resume/cancel/retry) don't have "data"
// to cache, but useMutation still replaces the manual `busy` useState +
// try/finally boilerplate that was scattered across NovelJobCard.tsx and
// downloads.tsx with consistent isPending/error state.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/task-manager";

export const queryKeys = {
  novels: ["novels"] as const,
  novel: (id: number) => ["novel", id] as const,
  novelChapters: (id: number) => ["novel", id, "chapters"] as const,
};

// --- reads -----------------------------------------------------------

export function useNovelsQuery() {
  return useQuery({ queryKey: queryKeys.novels, queryFn: api.listNovels });
}

export function useNovelQuery(novelId: number) {
  return useQuery({
    queryKey: queryKeys.novel(novelId),
    queryFn: () => api.getNovel(novelId),
    enabled: Number.isFinite(novelId),
  });
}

export function useNovelChaptersQuery(novelId: number) {
  return useQuery({
    queryKey: queryKeys.novelChapters(novelId),
    queryFn: () => api.getNovelChapters(novelId),
    enabled: Number.isFinite(novelId),
  });
}

// --- writes -----------------------------------------------------------

export function useScrapeNovelMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sourceUrl: string) => api.scrapeNovel(sourceUrl),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.novels });
    },
  });
}

export function useDeleteNovelMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (novelId: number) => api.deleteNovel(novelId),
    onSuccess: (_data, novelId) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.novels });
      queryClient.removeQueries({ queryKey: queryKeys.novel(novelId) });
    },
  });
}

export function useRetryFailedMutation() {
  return useMutation({ mutationFn: (group?: string) => api.retryFailed(group) });
}

export function useRetryTaskMutation() {
  return useMutation({ mutationFn: (taskId: string) => api.retryTask(taskId) });
}

export function useCancelJobMutation() {
  return useMutation({ mutationFn: (group: string) => api.cancelJob(group) });
}

export function useCancelTaskMutation() {
  return useMutation({ mutationFn: (taskId: string) => api.cancelTask(taskId) });
}

export function usePauseJobMutation() {
  return useMutation({
    mutationFn: ({ group, cancelRunning }: { group: string; cancelRunning?: boolean }) =>
      api.pauseJob(group, cancelRunning),
  });
}

export function useResumeJobMutation() {
  return useMutation({ mutationFn: (group: string) => api.resumeJob(group) });
}

export function usePauseQueueMutation() {
  return useMutation({ mutationFn: () => api.pauseQueue() });
}

export function useResumeQueueMutation() {
  return useMutation({ mutationFn: () => api.resumeQueue() });
}
