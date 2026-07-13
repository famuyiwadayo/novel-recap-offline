// taskManagerApi.ts
//
// Typed wrappers around every backend command from commands.py, plus the
// shared event payload types. One place to update if a command's
// signature changes, instead of pyInvoke("...", {...}) calls scattered
// across components with no compile-time check that you're passing the
// right shape.

import { Chapter, Novel, Task, TaskStats } from "@/types";
import { pyInvoke } from "tauri-plugin-pytauri-api";

export type Connectivity = { online: boolean };
export type QueuePaused = { paused: boolean };

export const api = {
  scrapeNovel: (sourceUrl: string) => pyInvoke<number>("scrape_novel", { source_url: sourceUrl }),

  downloadImage: (url: string, destPath: string, priority = 0) =>
    pyInvoke<string>("download_image", { url, dest_path: destPath, priority }),

  retryFailed: (group?: string) => pyInvoke<string[]>("retry_failed", { group }),
  retryTask: (taskId: string) => pyInvoke<boolean>("retry_task", { task_id: taskId }),

  cancelTask: (taskId: string) => pyInvoke<void>("cancel_task", { task_id: taskId }),
  cancelJob: (group: string) => pyInvoke<void>("cancel_job", { group }),

  pauseQueue: () => pyInvoke<void>("pause_queue", {}),
  resumeQueue: () => pyInvoke<void>("resume_queue", {}),

  pauseTask: (taskId: string, cancelRunning = false) =>
    pyInvoke<void>("pause_task", { task_id: taskId, cancel_running: cancelRunning }),
  resumeTask: (taskId: string) => pyInvoke<boolean>("resume_task", { task_id: taskId }),

  pauseJob: (group: string, cancelRunning = false) =>
    pyInvoke<void>("pause_job", { group, cancel_running: cancelRunning }),
  resumeJob: (group: string) => pyInvoke<string[]>("resume_job", { group }),

  getJobStats: (group?: string) => pyInvoke<TaskStats>("get_job_stats", { group }),
  getJobTasks: (group: string) => pyInvoke<Task[]>("get_job_tasks", { group }),
  getConnectivity: () => pyInvoke<Connectivity>("get_connectivity", {}),
  getQueuePaused: () => pyInvoke<QueuePaused>("get_queue_paused", {}),

  // --- library (persisted, SQLite-backed) ---
  listNovels: () => pyInvoke<Novel[]>("list_novels", {}),
  getNovel: (novelId: number) => pyInvoke<Novel | null>("get_novel", { novel_id: novelId }),
  getNovelChapters: (novelId: number) => pyInvoke<Chapter[]>("get_novel_chapters", { novel_id: novelId }),
  deleteNovel: (novelId: number) => pyInvoke<void>("delete_novel", { novel_id: novelId }),
  resumeNovel: (novelId: number) => pyInvoke<void>("resume_novel", { novel_id: novelId }),
};
