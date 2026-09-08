from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Callable, List, Optional

from models.schemas import AppError, TaskRecord, TaskStatus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_INDEX = PROJECT_ROOT / "data" / "index" / "tasks.json"

_gpu_lock = Lock()
_TERMINAL = {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}
_ALLOWED = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


def transition(
    task: TaskRecord,
    status: TaskStatus,
    *,
    stage: Optional[str] = None,
    message: Optional[str] = None,
    log_path: Optional[Path] = None,
) -> TaskRecord:
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


def run_gpu_task(task: TaskRecord, operation: Callable[[], None], *, log_path: Optional[Path] = None) -> TaskRecord:
    """Execute a synchronous GPU operation under the project-wide lock."""
    try_acquire_gpu()
    try:
        current = transition(task, TaskStatus.RUNNING, stage=task.stage, log_path=log_path)
        try:
            operation()
        except AppError as exc:
            return transition(current, TaskStatus.FAILED, message=exc.message, stage=exc.stage or current.stage)
        except Exception as exc:  # keep task state observable for unexpected subprocess errors
            return transition(current, TaskStatus.FAILED, message=str(exc))
        return transition(current, TaskStatus.SUCCEEDED, message="任务完成")
    finally:
        release_gpu()


def list_tasks(index_path: Path = TASK_INDEX) -> List[TaskRecord]:
    if not index_path.is_file():
        return []
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
        return [TaskRecord.model_validate(item) for item in raw] if isinstance(raw, list) else []
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def get_task(task_id: str, index_path: Path = TASK_INDEX) -> Optional[TaskRecord]:
    return next((item for item in list_tasks(index_path) if item.task_id == task_id), None)


def upsert_task(record: TaskRecord, index_path: Path = TASK_INDEX) -> TaskRecord:
    records = [item for item in list_tasks(index_path) if item.task_id != record.task_id]
    records.append(record)
    _write_task_index(index_path, records)
    return record


def recover_tasks(index_path: Path = TASK_INDEX) -> List[TaskRecord]:
    records = list_tasks(index_path)
    recovered: List[TaskRecord] = []
    changed = False
    for record in records:
        if record.status == TaskStatus.RUNNING:
            changed = True
            recovered.append(
                transition(
                    record,
                    TaskStatus.FAILED,
                    message="服务重启后无法恢复运行中的任务。",
                )
            )
        else:
            recovered.append(record)
    if changed:
        _write_task_index(index_path, recovered)
    return recovered


def try_acquire_gpu() -> None:
    if not _gpu_lock.acquire(blocking=False):
        raise AppError("GPU_BUSY", "已有模型任务正在执行，请等待它结束。")


def release_gpu() -> None:
    if _gpu_lock.locked():
        _gpu_lock.release()


def is_gpu_busy() -> bool:
    return _gpu_lock.locked()


def task_log_summary(task: Optional[TaskRecord]) -> tuple:
    if task is None or task.log_path is None:
        return [], "暂无日志。"
    root = (PROJECT_ROOT / "data" / "logs").resolve()
    path = task.log_path.resolve()
    if not path.is_relative_to(root):
        return [], "日志位于项目日志目录之外，未在页面读取。"
    try:
        if not path.is_file():
            return [], "当前阶段尚未写入日志。"
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - 12000))
            tail = handle.read(12000).decode("utf-8", errors="replace")
        stages = []
        prefix = task.task_id + "-"
        files = sorted((item for item in path.parent.iterdir()
                        if item.name.startswith(prefix) and item.suffix == ".log" and item.is_file()
                        and item.resolve().is_relative_to(root)), key=lambda item: item.stat().st_mtime_ns)
        for item in files:
            with item.open("r", encoding="utf-8", errors="replace") as handle:
                header = handle.read(4096)
            fields = dict(line.split(": ", 1) for line in header.partition("\nSTDOUT:")[0].splitlines() if ": " in line)
            stages.append([fields.get("STAGE", item.stem), fields.get("EXIT CODE", "未记录"),
                           fields.get("NOTE", fields.get("OUTPUT CHECK", "")), item.name])
        return stages, tail
    except OSError as exc:
        return [], f"日志暂不可读：{exc}"


def _write_task_index(index_path: Path, records: List[TaskRecord]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="tasks-", suffix=".json", dir=index_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump([item.model_dump(mode="json") for item in records], handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, index_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


__all__ = [
    "TASK_INDEX",
    "get_task",
    "list_tasks",
    "recover_tasks",
    "release_gpu",
    "run_gpu_task",
    "transition",
    "try_acquire_gpu",
    "upsert_task",
]
