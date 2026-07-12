import type { ExtractedChapter, NovelMetadata } from "./schema";

// export type TaskKind = "novel_discovery" | "chapter_fetch";

export enum TaskState {
  QUEUED = "QUEUED",
  RUNNING = "RUNNING",
  RETRYING = "RETRYING", //# failed, waiting on backoff before requeue
  PAUSED = "PAUSED", //# held out of the queue by pause_task()/pause_group()
  SUCCESS = "SUCCESS",
  DEAD = "DEAD", // # failed, retries exhausted — terminal
  CANCELLED = "CANCELLED",
}

export interface TaskStats {
  group: string | null;
  total: number;
  queued: number;
  running: number;
  retrying: number;
  paused: number;
  success: number;
  dead: number;
  cancelled: number;
}

export interface NovelDiscoveryTask {
  id: string;
  kind: "novel_discovery";
  group?: string;
  priority: number;
  state: TaskState;
  progress: number; //= 0.0  # 0..1, plugin-reported
  message: string;
  error?: string;
  retries: number;
  result: NovelMetadata | null;
}

export interface ExtractedChapterTask {
  id: string;
  kind: "chapter_fetch";
  group?: string;
  priority: number;
  state: TaskState;
  progress: number; //= 0.0  # 0..1, plugin-reported
  message: string;
  error?: string;
  retries: number;
  result: ExtractedChapter | null;
}

export type Task = NovelDiscoveryTask | ExtractedChapterTask;
export type TaskKind = Task["kind"];
