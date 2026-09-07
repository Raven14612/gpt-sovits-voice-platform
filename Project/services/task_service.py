from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from models.schemas import AppError, TaskRecord, TaskStatus

_gpu_lock = Lock()
_TERMINAL = {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}
_ALLOWED = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


def transition(task: TaskRecord, status: TaskStatus, *, stage: Optional[str] = None,
               message: Optional[str] = None, log_path: Optional[Path] = None) -> TaskRecord:
    """Return an updated task and reject impossible state changes."""
    if status != task.status and status not in _ALLOWED[task.status]:
        raise AppError("INVALID_TASK_STATE", f"任务不能从 {task.status.value} 转为 {status.value}。", stage=task.stage)
    now = datetime.now(timezone.utc)
    values = {"status": status, "updated_at": now}
    if stage is not None:
        values["stage"] = stage
    if message is not None:
        values["message"] = message
    if log_path is not None:
        values["log_path"] = log_path
    return task.model_copy(update=values)


def run_gpu_task(task: TaskRecord, operation, *, log_path: Optional[Path] = None) -> TaskRecord:
    """Execute a synchronous GPU operation under the project-wide lock."""
    try_acquire_gpu()
    current = transition(task, TaskStatus.RUNNING, stage=task.stage, log_path=log_path)
    try:
        operation()
    except AppError as exc:
        return transition(current, TaskStatus.FAILED, message=exc.message, stage=exc.stage or current.stage)
    except Exception as exc:  # keep task state observable for unexpected subprocess errors
        return transition(current, TaskStatus.FAILED, message=str(exc))
    finally:
        release_gpu()
    return transition(current, TaskStatus.SUCCEEDED, message="任务完成")


def try_acquire_gpu() -> None:
    if not _gpu_lock.acquire(blocking=False):
        raise AppError("GPU_BUSY", "已有模型任务正在执行，请等待它结束。")


def release_gpu() -> None:
    if _gpu_lock.locked():
        _gpu_lock.release()
