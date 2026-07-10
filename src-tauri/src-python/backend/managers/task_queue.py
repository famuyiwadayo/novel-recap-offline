"""
Generic priority task queue / download manager engine.

No domain knowledge here (no novels, no images) — this file only knows about
"tasks" that get dispatched to registered "plugins" by a `kind` string. Two
other modules build on this:

  - plugins.py: actual plugins (image download, wtr-lab scraping, etc.)
  - app_wiring.py: pytauri commands + event emission

Core features ("all the necessary sugars"):
  - Priority queue: lower `priority` value runs first; stable FIFO within
    the same priority via a monotonic sequence number.
  - Retry with exponential backoff, capped, per-task configurable.
  - Dead-letter: tasks that exhaust retries land in DEAD, not silently lost.
  - requeue() / requeue_failed(): manual retry, single or bulk (by group).
  - Cancellation: cooperative, via anyio CancelScope per running task.
  - Pause / resume: workers stop pulling new tasks, in-flight tasks finish.
  - Dynamic task spawning: a plugin can return child tasks to enqueue
    (e.g. "discover novel" spawns N "fetch chapter" tasks).
  - Grouping: tasks can share a `group` id (e.g. one per novel/job) so you
    can query/retry/cancel a whole job at once.
  - Subscriptions: on_task() for per-task updates, on_stats() for
    aggregate group counts — wire these to UI or Tauri events.
"""

from __future__ import annotations

import heapq
import itertools
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Any, Callable, ClassVar, List, Dict, Optional

import anyio
from anyio.abc import TaskGroup

# ============================================================================
# Task model
# ============================================================================


class TaskState(Enum):
    QUEUED = auto()
    RUNNING = auto()
    RETRYING = auto()  # failed, waiting on backoff before requeue
    SUCCESS = auto()
    DEAD = auto()  # failed, retries exhausted — terminal
    CANCELLED = auto()


@dataclass
class Task:
    kind: str  # plugin lookup key
    payload: Any = None  # whatever the plugin needs
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    priority: int = 0  # lower = runs first
    group: Optional[str] = None  # e.g. a job/novel id
    max_retries: int = 3
    retry_base_delay: float = 1.0  # seconds
    retry_max_delay: float = 30.0  # seconds

    # mutable status fields
    retries: int = 0
    state: TaskState = TaskState.QUEUED
    progress: float = 0.0  # 0..1, plugin-reported
    message: str = ""
    error: Optional[str] = None
    result: Any = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class PluginResult:
    data: Any = None
    spawn: List[Task] = field(default_factory=list)  # child tasks to enqueue


ProgressFn = Callable[[float, str], None]


class Plugin(ABC):
    """Subclass and set `kind` to a unique string. Register with
    TaskQueueManager.register_plugin(). One plugin instance handles all
    tasks of that kind."""

    kind: ClassVar[str]

    @abstractmethod
    async def run(self, task: Task, report_progress: ProgressFn) -> PluginResult:
        """Do the work for `task`. Raise on failure — the manager handles
        retry/dead-lettering. Call report_progress(0.0-1.0, message) as
        often as makes sense; it's fine to never call it for quick tasks."""
        ...


@dataclass
class GroupStats:
    group: Optional[str]
    total: int = 0
    queued: int = 0
    running: int = 0
    retrying: int = 0
    success: int = 0
    dead: int = 0
    cancelled: int = 0


TaskListener = Callable[[Task], None]
StatsListener = Callable[[GroupStats], None]

# ============================================================================
# Async priority queue (heap + condition variable, anyio-backend agnostic)
# ============================================================================


class _QueueClosed(Exception):
    pass


@dataclass(order=True)
class _Entry:
    priority: int
    seq: int
    task: Task = field(compare=False)


class _AsyncPriorityQueue:
    def __init__(self) -> None:
        self._heap: List[_Entry] = []
        self._seq = itertools.count()
        self._condition = anyio.Condition()
        self._closed = False

    async def put(self, task: Task) -> None:
        async with self._condition:
            heapq.heappush(self._heap, _Entry(task.priority, next(self._seq), task))
            self._condition.notify()

    async def get(self) -> Task:
        async with self._condition:
            while not self._heap:
                if self._closed:
                    raise _QueueClosed()
                await self._condition.wait()
            return heapq.heappop(self._heap).task

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()


# ============================================================================
# Manager
# ============================================================================


class TaskQueueManager:
    def __init__(self, num_workers: int = 5) -> None:
        self.num_workers = num_workers
        self._plugins: Dict[str, Plugin] = {}
        self._tasks: Dict[str, Task] = {}
        self._queue = _AsyncPriorityQueue()
        self._scopes: Dict[str, anyio.CancelScope] = {}
        self._task_listeners: List[TaskListener] = []
        self._stats_listeners: List[StatsListener] = []
        self._resume_event = anyio.Event()
        self._resume_event.set()  # start unpaused
        self._task_group: Optional[TaskGroup] = None
        self._stopping = False

    # --- plugin registration -------------------------------------------------

    def register_plugin(self, plugin: Plugin) -> None:
        self._plugins[plugin.kind] = plugin

    # --- subscriptions --------------------------------------------------------

    def on_task(self, cb: TaskListener) -> Callable[[], None]:
        self._task_listeners.append(cb)
        return lambda: (
            self._task_listeners.remove(cb) if cb in self._task_listeners else None
        )

    def on_stats(self, cb: StatsListener) -> Callable[[], None]:
        self._stats_listeners.append(cb)
        return lambda: (
            self._stats_listeners.remove(cb) if cb in self._stats_listeners else None
        )

    # --- reads ------------------------------------------------------------

    def get_tasks(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def tasks_in_group(self, group: Optional[str]) -> List[Task]:
        return [t for t in self._tasks.values() if t.group == group]

    def stats(self, group: Optional[str] = None) -> GroupStats:
        tasks = (
            self.tasks_in_group(group)
            if group is not None
            else list(self._tasks.values())
        )

        s = GroupStats(group=group, total=len(tasks))
        for t in tasks:
            if t.state == TaskState.QUEUED:
                s.queued += 1
            elif t.state == TaskState.RUNNING:
                s.running += 1
            elif t.state == TaskState.RETRYING:
                s.retrying += 1
            elif t.state == TaskState.SUCCESS:
                s.success += 1
            elif t.state == TaskState.DEAD:
                s.dead += 1
            elif t.state == TaskState.CANCELLED:
                s.cancelled += 1
        return s

    # --- internal: mutate + notify ------------------------------------------

    def _set_task(self, task_id: str, **kwargs) -> Task:
        current = self._tasks[task_id]
        updated = replace(current, updated_at=time.time(), **kwargs)
        self._tasks[task_id] = updated

        for cb in list(self._task_listeners):
            cb(updated)
        stats = self.stats(updated.group)
        for cb in list(self._stats_listeners):
            cb(stats)
        return updated

    # --- enqueue / spawn -----------------------------------------------------

    async def enqueue(
        self,
        kind: str,
        payload: Any = None,
        *,
        priority: int = 0,
        group: Optional[str] = None,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        retry_max_delay: float = 30.0,
        task_id: Optional[str] = None,
    ) -> Task:

        task = Task(
            kind=kind,
            payload=payload,
            id=task_id or str(uuid.uuid4()),
            priority=priority,
            group=group,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
            retry_max_delay=retry_max_delay,
        )
        return await self._enqueue_task(task)

    async def _enqueue_task(self, task: Task) -> Task:
        self._tasks[task.id] = task
        for cb in list(self._task_listeners):
            cb(task)
        for cb in list(self._stats_listeners):
            cb(self.stats(task.group))
        await self._queue.put(task)
        return task

    # --- retry sugar --------------------------------------------------------

    async def requeue(self, task_id: str) -> bool:
        """Manually retry one task right now (bypasses backoff). Works on
        DEAD or CANCELLED tasks. Returns False if task_id is unknown."""

        task = self._tasks.get(task_id)
        if task is None:
            return False
        task = self._set_task(task_id, state=TaskState.QUEUED, error=None, progress=0.0)
        await self._queue.put(task)
        return True

    async def requeue_failed(self, group: Optional[str] = None) -> List[str]:
        """Bulk-retry every DEAD task, optionally scoped to one group.
        Returns the ids that were requeued."""
        dead = (
            [t.id for t in self.tasks_in_group(group) if t.state == TaskState.DEAD]
            if group is not None
            else [t.id for t in self._tasks.values() if t.state == TaskState.DEAD]
        )

        for tid in dead:
            await self.requeue(tid)
        return dead

    # --- cancellation --------------------------------------------------------

    def cancel(self, task_id: str) -> None:
        """Cancel a task. If it's already running, its plugin gets a
        cancellation signal via anyio; if still queued, it's marked
        CANCELLED and skipped when it comes off the queue."""

        scope = self._scopes.get(task_id)
        if scope is not None:
            scope.cancel()
        elif task_id in self._tasks:
            self._set_task(task_id, state=TaskState.CANCELLED)

    def cancel_group(self, group: str) -> None:
        for t in self.tasks_in_group(group):
            if t.state in (TaskState.RUNNING, TaskState.QUEUED, TaskState.RETRYING):
                self.cancel(t.id)

    # --- pause / resume ------------------------------------------------------

    def pause(self) -> None:
        self._resume_event = anyio.Event()

    def resume(self) -> None:
        self._resume_event.set()

    @property
    def is_paused(self) -> bool:
        return not self._resume_event.is_set()

    # --- run loop --------------------------------------------------------

    async def start(self) -> None:
        """Runs forever (until stop()). Call once, e.g. from your app's
        startup, via `task_group.start_soon(manager.start)`."""
        self._stopping = False
        async with anyio.create_task_group() as tg:
            self._task_group = tg
            for _ in range(self.num_workers):
                tg.start_soon(self._worker)

    async def stop(self) -> None:
        self._stopping = True
        await self._queue.close()

    async def _worker(self) -> None:
        while True:
            # honor pause: re-read the current event each loop iteration
            await self._resume_event.wait()
            try:
                task = await self._queue.get()
            except _QueueClosed:
                return
            if task.state == TaskState.CANCELLED:
                continue
            await self._run_task(task)

    async def _run_task(self, task: Task) -> None:
        plugin = self._plugins.get(task.kind)
        if plugin is None:
            self._set_task(
                task.id,
                state=TaskState.DEAD,
                error=f"No plugin registered for kind={task.kind!r}",
            )
            return

        task = self._set_task(task.id, state=TaskState.RUNNING, error=None)
        scope = anyio.CancelScope()
        self._scopes[task.id] = scope

        def report_progress(progress: float, message: str = "") -> None:
            self._set_task(
                task.id, progress=max(0.0, min(1.0, progress)), message=message
            )

        result: Optional[PluginResult] = None
        error: Optional[str] = None
        with scope:
            try:
                result = await plugin.run(task, report_progress)
            except Exception as exc:
                error = str(exc)

        self._scopes.pop(task.id, None)

        if scope.cancelled_caught:
            self._set_task(task.id, state=TaskState.CANCELLED)
            return

        if error is not None:
            await self._handle_failure(task, error)
            return

        self._set_task(
            task.id,
            state=TaskState.SUCCESS,
            progress=1.0,
            result=result.data if result else None,
        )
        for child in result.spawn if result else []:
            if self._task_group is not None:
                self._task_group.start_soon(self._enqueue_task, child)

    async def _handle_failure(self, task: Task, error: str) -> None:
        retries = task.retries + 1
        if retries > task.max_retries:
            self._set_task(task.id, state=TaskState.DEAD, error=error, retries=retries)
            return
        self._set_task(task.id, state=TaskState.RETRYING, error=error, retries=retries)
        delay = min(task.retry_base_delay * (2 ** (retries - 1)), task.retry_max_delay)
        if self._task_group is not None:
            self._task_group.start_soon(self._delayed_requeue, task.id, delay)

    async def _delayed_requeue(self, task_id: str, delay: float) -> None:
        await anyio.sleep(delay)
        task = self._tasks.get(task_id)
        # only requeue if nothing else changed its state in the meantime
        # (e.g. it wasn't cancelled while waiting on backoff)
        if task and task.state == TaskState.RETRYING:
            task = self._set_task(task_id, state=TaskState.QUEUED)
            await self._queue.put(task)
