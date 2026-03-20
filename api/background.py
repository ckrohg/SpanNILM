"""Simple in-memory background task runner using Python threading."""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class BackgroundTask:
    task_id: str
    status: str = "pending"  # pending, running, completed, failed
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict = field(default_factory=dict)
    error: str | None = None


# In-memory task store (no persistence needed — Railway restarts clear it)
_tasks: dict[str, BackgroundTask] = {}
_lock = threading.Lock()


def run_in_background(task_id: str, func, *args, **kwargs) -> BackgroundTask:
    """Run a function in a background thread. Returns immediately."""
    task = BackgroundTask(task_id=task_id)
    with _lock:
        _tasks[task_id] = task

    def _wrapper():
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        try:
            result = func(*args, **kwargs)
            task.result = result or {}
            task.status = "completed"
        except Exception as e:
            task.error = str(e)
            task.status = "failed"
        finally:
            task.completed_at = datetime.now(timezone.utc)

    thread = threading.Thread(target=_wrapper, daemon=True)
    thread.start()
    return task


def get_task(task_id: str) -> BackgroundTask | None:
    with _lock:
        return _tasks.get(task_id)
