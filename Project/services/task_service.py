from __future__ import annotations

from threading import Lock

from models.schemas import AppError

_gpu_lock = Lock()


def try_acquire_gpu() -> None:
    if not _gpu_lock.acquire(blocking=False):
        raise AppError("GPU_BUSY", "已有模型任务正在执行，请等待它结束。")


def release_gpu() -> None:
    if _gpu_lock.locked():
        _gpu_lock.release()

