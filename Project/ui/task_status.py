from __future__ import annotations

from typing import Optional

from models.schemas import AppError, TaskRecord, TaskStatus
from services import dataset_service, task_service
import gradio as gr


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


def error_text(exc: Exception) -> str:
    if isinstance(exc, AppError):
        message = gpu_busy_text() if exc.code == "GPU_BUSY" else exc.message
        return f"{exc.code}：{message}"
    return f"操作失败：{exc}"


def refresh_status(active_task, dataset_id, submitting, notice):
    records = sorted(task_service.list_tasks(), key=lambda item: item.updated_at, reverse=True)
    task = next((item for item in records if item.task_id == active_task), None)
    busy = task_service.is_gpu_busy()
    running = task is not None and task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}
    dataset = dataset_service.get_dataset(dataset_id) if dataset_id else None
    enabled = dataset is not None and not (busy or submitting or running)
    stages, log = task_service.task_log_summary(task)
    message = task_status_text(task)
    if notice:
        message = notice + "\n\n" + message
    if busy:
        message = gpu_busy_text() + "\n\n" + message
    choices = [(f"{item.task_id} · {item.status.value}", item.task_id) for item in records]
    return (gr.update(choices=choices, value=task.task_id if task else None), message, stages, log,
            gr.update(interactive=enabled), gr.update(interactive=enabled))
