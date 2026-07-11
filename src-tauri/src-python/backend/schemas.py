"""
Pydantic models for IPC — everything that crosses the Tauri boundary
(command return types, emitted events) lives here, plus the small mapping
functions that turn internal dataclasses (Task, GroupStats) into these.

No dependency on app.py or commands.py — both of those import FROM here,
never the other way around.
"""

from typing import Any, Optional

from pydantic import BaseModel

from backend.managers.task_queue import Task, GroupStats


class TaskPayload(BaseModel):
    id: str
    kind: str
    group: Optional[str]
    priority: int
    state: str
    progress: float
    message: str
    error: Optional[str]
    retries: int
    result: Any


class StatsPayload(BaseModel):
    group: Optional[str]
    total: int
    queued: int
    running: int
    retrying: int
    paused: int
    success: int
    dead: int
    cancelled: int


class ConnectivityPayload(BaseModel):
    online: bool


def task_payload(t: Task) -> TaskPayload:
    return TaskPayload(
        id=t.id,
        kind=t.kind,
        group=t.group,
        priority=t.priority,
        state=t.state.name,
        progress=t.progress,
        message=t.message,
        error=t.error,
        retries=t.retries,
        result=t.result,
    )


def stats_payload(s: GroupStats) -> StatsPayload:
    return StatsPayload(
        group=s.group,
        total=s.total,
        queued=s.queued,
        running=s.running,
        retrying=s.retrying,
        paused=s.paused,
        success=s.success,
        dead=s.dead,
        cancelled=s.cancelled,
    )
