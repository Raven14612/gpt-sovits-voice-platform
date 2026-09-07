from __future__ import annotations

from typing import Optional

from models.schemas import TaskRecord, TaskStatus


def task_status_text(task: Optional[TaskRecord]) -> str:
    if task is None:
        return "当前没有任务。"
    labels = {
        TaskStatus.PENDING: "等待",
        TaskStatus.RUNNING: "执行中",
        TaskStatus.SUCCEEDED: "成功",
        TaskStatus.FAILED: "失败",
        TaskStatus.CANCELLED: "已取消",
    }
    detail = f"\n阶段：{task.stage}" if task.stage else ""
    if task.log_path:
        detail += f"\n日志：{task.log_path}"
    return f"状态：{labels[task.status]}\n{task.message}{detail}"


def gpu_busy_text() -> str:
    return "已有任务正在运行，请等待当前 GPU 任务结束。"
