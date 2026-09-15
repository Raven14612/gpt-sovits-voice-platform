from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence, Mapping, Optional

from models.schemas import AppError, TaskRecord, TaskStatus
from services.task_service import release_gpu, transition, try_acquire_gpu
from services.project_paths import project_environment
from services.process_control import run_owned_command

DATA_PIPELINE_STAGES = (
    "validating",
    "slicing",
    "asr",
    "feature_text",
    "feature_hubert",
    "feature_semantic",
)


@dataclass(frozen=True)
class StagePlan:
    stage: str
    command: Sequence[str]
    cwd: Path
    outputs: Sequence[Path]
    timeout: int = 3600
    gpu: bool = True


class PipelineRunner:
    """Config-driven subprocess stages; the caller supplies the adapter commands."""

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def run_pipeline(self, task: TaskRecord, stages: Sequence[StagePlan]) -> TaskRecord:
        _validate_pipeline_stages(stages)
        current = task
        total = len(stages)
        for index, plan in enumerate(stages):
            current = self.run_stage(
                current,
                plan.stage,
                plan.command,
                cwd=plan.cwd,
                outputs=plan.outputs,
                timeout=plan.timeout,
                gpu=plan.gpu,
                final=index == total - 1,
            )
            if current.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
                return current
        return current

    def run_stage(
        self,
        task: TaskRecord,
        stage: str,
        command: Sequence[str],
        *,
        cwd: Path,
        outputs: Sequence[Path],
        timeout: int = 3600,
        gpu: bool = True,
        final: bool = True,
        env: Optional[Mapping[str, str]] = None,
    ) -> TaskRecord:
        log_path = self.log_dir / ("%s-%s.log" % (task.task_id, stage))
        acquired_gpu = False
        current = transition(task, TaskStatus.RUNNING, stage=stage, message="开始执行", log_path=log_path)

        try:
            if gpu:
                try:
                    try_acquire_gpu()
                    acquired_gpu = True
                except AppError as exc:
                    _write_stage_log(
                        log_path,
                        stage=stage,
                        command=command,
                        cwd=cwd,
                        timeout=timeout,
                        note="GPU_BUSY: %s" % exc.message,
                    )
                    return transition(current, TaskStatus.FAILED, message=exc.message)

            completed = run_owned_command(
                list(command),
                cwd=cwd,
                env=env if env is not None else project_environment(python=command[0], engine_root=cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            stdout = _to_text(completed.stdout)
            stderr = _to_text(completed.stderr)
            missing = _missing_outputs(outputs)
            _write_stage_log(
                log_path,
                stage=stage,
                command=command,
                cwd=cwd,
                timeout=timeout,
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                missing_outputs=missing,
            )
            if completed.returncode != 0:
                return transition(current, TaskStatus.FAILED, message="阶段退出码：%s" % completed.returncode)
            if missing:
                return transition(current, TaskStatus.FAILED, message="输出缺失：%s" % ", ".join(missing))
            if final:
                return transition(current, TaskStatus.SUCCEEDED, message="阶段完成")
            return transition(current, TaskStatus.RUNNING, message="阶段完成")
        except subprocess.TimeoutExpired as exc:
            stdout = _to_text(getattr(exc, "stdout", ""))
            stderr = _to_text(getattr(exc, "stderr", ""))
            _write_stage_log(
                log_path,
                stage=stage,
                command=command,
                cwd=cwd,
                timeout=timeout,
                note="TIMEOUT",
                stdout=stdout,
                stderr=stderr,
            )
            return transition(current, TaskStatus.FAILED, message="阶段超时")
        except OSError as exc:
            _write_stage_log(
                log_path,
                stage=stage,
                command=command,
                cwd=cwd,
                timeout=timeout,
                note="OSERROR: %s" % exc,
            )
            return transition(current, TaskStatus.FAILED, message=str(exc))
        finally:
            if acquired_gpu:
                release_gpu()


def validate_stage_output(paths: Sequence[Path]) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise AppError("OUTPUT_INVALID", "阶段输出不存在：%s" % ", ".join(missing))


def _validate_pipeline_stages(stages: Sequence[StagePlan]) -> None:
    actual = [plan.stage for plan in stages]
    expected = list(DATA_PIPELINE_STAGES)
    if actual != expected:
        raise AppError(
            "INVALID_STAGE_SEQUENCE",
            "pipeline stages must match the required order: %s" % ", ".join(expected),
        )


def _missing_outputs(paths: Sequence[Path]) -> Sequence[str]:
    return [str(path) for path in paths if not path.is_file()]


def _to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _write_stage_log(
    path: Path,
    *,
    stage: str,
    command: Sequence[str],
    cwd: Path,
    timeout: int,
    returncode: object = None,
    stdout: str = "",
    stderr: str = "",
    missing_outputs: Iterable[str] = (),
    note: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("STAGE: %s\n" % stage)
        handle.write("COMMAND: %s\n" % json.dumps(list(command), ensure_ascii=False))
        handle.write("CWD: %s\n" % cwd)
        handle.write("TIMEOUT: %s\n" % timeout)
        if note:
            handle.write("NOTE: %s\n" % note)
        if returncode is not None:
            handle.write("EXIT CODE: %s\n" % returncode)
        missing_outputs = list(missing_outputs)
        if missing_outputs:
            handle.write("OUTPUT CHECK: missing=%s\n" % json.dumps(missing_outputs, ensure_ascii=False))
        handle.write("STDOUT:\n")
        if stdout:
            handle.write(stdout)
            if not stdout.endswith("\n"):
                handle.write("\n")
        handle.write("STDERR:\n")
        if stderr:
            handle.write(stderr)
            if not stderr.endswith("\n"):
                handle.write("\n")


__all__ = [
    "DATA_PIPELINE_STAGES",
    "PipelineRunner",
    "StagePlan",
    "validate_stage_output",
]
