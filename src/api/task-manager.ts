// taskManagerApi.ts
//
// Typed wrappers around every backend command from commands.py, plus the
// shared event payload types. One place to update if a command's
// signature changes, instead of pyInvoke("...", {...}) calls scattered
// across components with no compile-time check that you're passing the
// right shape.

import { Task, TaskStats } from "@/types";
import { pyInvoke } from "tauri-plugin-pytauri-api";

export type Connectivity = { online: boolean };
export type QueuePaused = { paused: boolean };

export const api = {
  scrapeNovel: (novelId: number, sourceUrl: string) =>
    pyInvoke<void>("scrape_novel", { novel_id: novelId, source_url: sourceUrl }),

  downloadImage: (url: string, destPath: string, priority = 0) =>
    pyInvoke<string>("download_image", { url, destPath, priority }),

  retryFailed: (group?: string) => pyInvoke<string[]>("retry_failed", { group }),
  retryTask: (taskId: string) => pyInvoke<boolean>("retry_task", { taskId }),

  cancelTask: (taskId: string) => pyInvoke<void>("cancel_task", { taskId }),
  cancelJob: (group: string) => pyInvoke<void>("cancel_job", { group }),

  pauseQueue: () => pyInvoke<void>("pause_queue", {}),
  resumeQueue: () => pyInvoke<void>("resume_queue", {}),

  pauseTask: (taskId: string, cancelRunning = false) => pyInvoke<void>("pause_task", { taskId, cancelRunning }),
  resumeTask: (taskId: string) => pyInvoke<boolean>("resume_task", { taskId }),

  pauseJob: (group: string, cancelRunning = false) => pyInvoke<void>("pause_job", { group, cancelRunning }),
  resumeJob: (group: string) => pyInvoke<string[]>("resume_job", { group }),

  getJobStats: (group?: string) => pyInvoke<TaskStats>("get_job_stats", { group }),
  getJobTasks: (group: string) => pyInvoke<Task[]>("get_job_tasks", { group }),
  getConnectivity: () => pyInvoke<Connectivity>("get_connectivity", {}),
  getQueuePaused: () => pyInvoke<QueuePaused>("get_queue_paused", {}),
};
