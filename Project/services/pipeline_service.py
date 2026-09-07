from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from models.schemas import AppError, TaskRecord, TaskStatus
from services.task_service import transition, try_acquire_gpu, release_gpu


class PipelineRunner:
    """Config-driven subprocess stages; the caller supplies the adapter commands."""

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def run_stage(self, task: TaskRecord, stage: str, command: Sequence[str], *,
                  cwd: Path, outputs: Sequence[Path], timeout: int = 3600,
                  gpu: bool = True) -> TaskRecord:
        log_path = self.log_dir / f"{task.task_id}-{stage}.log"
        if gpu:
            try_acquire_gpu()
        current = transition(task, TaskStatus.RUNNING, stage=stage, message="开始执行", log_path=log_path)
        try:
            with log_path.open("w", encoding="utf-8") as log:
                completed = subprocess.run(list(command), cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                           timeout=timeout, check=False)
            if completed.returncode != 0:
                return transition(current, TaskStatus.FAILED, message=f"阶段退出码：{completed.returncode}")
            missing = [str(path) for path in outputs if not path.exists()]
            if missing:
                return transition(current, TaskStatus.FAILED, message=f"输出缺失：{', '.join(missing)}")
            return transition(current, TaskStatus.SUCCEEDED, message="阶段完成")
        except subprocess.TimeoutExpired:
            return transition(current, TaskStatus.FAILED, message="阶段超时")
        except OSError as exc:
            return transition(current, TaskStatus.FAILED, message=str(exc))
        finally:
            if gpu:
                release_gpu()


def validate_stage_output(paths: Sequence[Path]) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise AppError("OUTPUT_INVALID", f"阶段输出不存在：{', '.join(missing)}")
