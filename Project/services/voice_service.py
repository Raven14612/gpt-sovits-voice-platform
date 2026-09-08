from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Union
from uuid import uuid4

from models.schemas import AppError, DatasetRecord, EmotionReference, TaskRecord, TaskStatus, VoiceProfile
from services.pipeline_service import PipelineRunner
from services.task_service import TASK_INDEX, release_gpu, transition, try_acquire_gpu, upsert_task

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VOICE_INDEX = PROJECT_ROOT / "data" / "index" / "voices.json"
VOICE_ARCHIVE_ROOT = PROJECT_ROOT / "data" / "voices"
DEFAULT_LOG_DIR = PROJECT_ROOT / "data" / "logs" / "training"


def list_voice_profiles(index_path: Path = VOICE_INDEX) -> List[VoiceProfile]:
    if not index_path.is_file():
        return []
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
        return [VoiceProfile.model_validate(item) for item in raw] if isinstance(raw, list) else []
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def get_voice_profile(voice_id: str, index_path: Path = VOICE_INDEX) -> Optional[VoiceProfile]:
    return next((item for item in list_voice_profiles(index_path) if item.voice_id == voice_id), None)


def upsert_voice_profile(record: VoiceProfile, index_path: Path = VOICE_INDEX) -> VoiceProfile:
    records = [item for item in list_voice_profiles(index_path) if item.voice_id != record.voice_id]
    records.append(record)
    _write_json_index(index_path, records)
    return record


def list_voices(index_path: Path = VOICE_INDEX) -> List[VoiceProfile]:
    return list_voice_profiles(index_path)


def get_voice(voice_id: str, index_path: Path = VOICE_INDEX) -> Optional[VoiceProfile]:
    return get_voice_profile(voice_id, index_path)


def train_voice(
    dataset: Union[DatasetRecord, Mapping[str, Any]],
    voice_id: str,
    params: Mapping[str, Any],
) -> TaskRecord:
    plan = _parse_training_params(params)
    if plan.gpt_command is None or plan.sovits_command is None:
        raise AppError("NOT_IMPLEMENTED", "训练引擎尚未接入，缺少 GPT/SoVITS stage command。", stage="training")

    dataset_record = _coerce_dataset(dataset)
    log_dir = plan.log_dir or DEFAULT_LOG_DIR
    runner = PipelineRunner(log_dir)
    acquired = False
    try:
        try_acquire_gpu()
        acquired = True

        task = TaskRecord(
            task_id=plan.task_id or f"train-{voice_id}-{uuid4().hex}",
            kind="train_voice",
            stage="train_gpt",
            message="等待执行",
        )
        upsert_task(task, plan.task_index)

        current = transition(task, TaskStatus.RUNNING, stage="train_gpt", message="开始执行")
        upsert_task(current, plan.task_index)
        current = runner.run_stage(
            current,
            "train_gpt",
            plan.gpt_command,
            cwd=plan.gpt_cwd,
            outputs=plan.gpt_outputs,
            timeout=plan.gpt_timeout,
            gpu=False,
            final=False,
        )
        upsert_task(current, plan.task_index)
        if current.status != TaskStatus.RUNNING:
            return current

        current = transition(current, TaskStatus.RUNNING, stage="train_sovits", message="开始执行")
        upsert_task(current, plan.task_index)
        current = runner.run_stage(
            current,
            "train_sovits",
            plan.sovits_command,
            cwd=plan.sovits_cwd,
            outputs=plan.sovits_outputs,
            timeout=plan.sovits_timeout,
            gpu=False,
            final=False,
        )
        upsert_task(current, plan.task_index)
        if current.status != TaskStatus.RUNNING:
            return current

        try:
            gpt_weight = _validate_checkpoint_file(plan.gpt_weight_path, plan.allowed_roots)
            sovits_weight = _validate_checkpoint_file(plan.sovits_weight_path, plan.allowed_roots)
            archived_gpt = _archive_weight(gpt_weight, plan.archive_root, voice_id)
            archived_sovits = _archive_weight(sovits_weight, plan.archive_root, voice_id)

            profile = VoiceProfile(
                voice_id=voice_id,
                display_name=plan.display_name or voice_id,
                feature_name=plan.feature_name or voice_id,
                dataset_id=dataset_record.dataset_id,
                gpt_weight=archived_gpt,
                sovits_weight=archived_sovits,
                references=plan.references,
                engine_profile=plan.engine_profile,
                status="verified",
            )
            upsert_voice_profile(profile, plan.voice_index)
        except AppError as exc:
            failed = transition(current, TaskStatus.FAILED, stage=exc.stage or "packaging", message=exc.message)
            upsert_task(failed, plan.task_index)
            return failed
        except Exception as exc:
            failed = transition(current, TaskStatus.FAILED, stage="packaging", message=str(exc))
            upsert_task(failed, plan.task_index)
            return failed

        final = transition(current, TaskStatus.SUCCEEDED, stage="packaging", message="训练完成")
        upsert_task(final, plan.task_index)
        return final
    finally:
        if acquired:
            release_gpu()


def _coerce_dataset(dataset: Union[DatasetRecord, Mapping[str, Any]]) -> DatasetRecord:
    if isinstance(dataset, DatasetRecord):
        return dataset
    return DatasetRecord.model_validate(dataset)


def _parse_training_params(params: Mapping[str, Any]) -> "_TrainingPlan":
    gpt_command = _as_command(params.get("gpt_command"))
    if gpt_command is None:
        return _TrainingPlan(gpt_command=None)
    gpt_cwd = _as_path(params.get("gpt_cwd"), "gpt_cwd")
    gpt_outputs = _as_paths(params.get("gpt_outputs"), "gpt_outputs")
    if not gpt_outputs and params.get("gpt_weight_path") is None:
        raise AppError("NOT_IMPLEMENTED", "训练引擎尚未接入，缺少 GPT stage output path。", stage="train_gpt")
    gpt_weight_path = _as_path(params.get("gpt_weight_path", gpt_outputs[0] if gpt_outputs else None), "gpt_weight_path")

    allowed_roots = _as_paths(params.get("allowed_roots", []), "allowed_roots")
    archive_root = _as_path(params.get("archive_root", VOICE_ARCHIVE_ROOT), "archive_root")
    allowed_roots = [archive_root, gpt_cwd, *allowed_roots]

    sovits_command = _as_command(params.get("sovits_command"))
    sovits_cwd = _as_path(params.get("sovits_cwd", gpt_cwd), "sovits_cwd")
    sovits_outputs = _as_paths(params.get("sovits_outputs", []), "sovits_outputs")
    if sovits_command is not None and not sovits_outputs and params.get("sovits_weight_path") is None:
        raise AppError("NOT_IMPLEMENTED", "训练引擎尚未接入，缺少 SoVITS stage output path。", stage="train_sovits")
    sovits_weight_path = _as_path(
        params.get("sovits_weight_path", sovits_outputs[0] if sovits_outputs else None),
        "sovits_weight_path",
    ) if sovits_outputs or params.get("sovits_weight_path") is not None else None

    references = [_coerce_reference(item) for item in params.get("references", [])]
    return _TrainingPlan(
        task_id=str(params.get("task_id") or "") or None,
        display_name=str(params.get("display_name") or "") or None,
        feature_name=str(params.get("feature_name") or "") or None,
        engine_profile=str(params.get("engine_profile") or "local-gpt-sovits"),
        gpt_command=gpt_command,
        gpt_cwd=gpt_cwd,
        gpt_outputs=gpt_outputs,
        gpt_timeout=int(params.get("gpt_timeout", params.get("timeout", 3600))),
        gpt_weight_path=gpt_weight_path,
        sovits_command=sovits_command,
        sovits_cwd=sovits_cwd,
        sovits_outputs=sovits_outputs,
        sovits_timeout=int(params.get("sovits_timeout", params.get("timeout", 3600))),
        sovits_weight_path=sovits_weight_path,
        archive_root=archive_root,
        allowed_roots=allowed_roots,
        log_dir=_optional_path(params.get("log_dir"), "log_dir") or DEFAULT_LOG_DIR,
        task_index=_optional_path(params.get("task_index"), "task_index") or TASK_INDEX,
        voice_index=_optional_path(params.get("voice_index"), "voice_index") or VOICE_INDEX,
        references=references,
    )


def _coerce_reference(value: Any) -> EmotionReference:
    if isinstance(value, EmotionReference):
        return value
    return EmotionReference.model_validate(value)


def _as_command(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        command = [str(item) for item in value]
        if not command:
            return None
        return command
    raise AppError("NOT_IMPLEMENTED", "训练命令必须显式以参数数组提供。", stage="training")


def _as_paths(value: Any, field_name: str) -> List[Path]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        paths = [_as_path(item, field_name) for item in value]
        return paths
    if field_name == "allowed_roots" and isinstance(value, (str, Path)):
        return [_as_path(value, field_name)]
    raise AppError("NOT_IMPLEMENTED", f"{field_name} 必须显式提供为路径列表。", stage="training")


def _as_path(value: Any, field_name: str) -> Path:
    if value is None:
        raise AppError("NOT_IMPLEMENTED", f"训练引擎尚未接入，缺少 {field_name}。", stage="training")
    path = Path(value).expanduser().resolve()
    if not path.is_absolute():
        raise AppError("OUTPUT_INVALID", f"{field_name} 必须是绝对路径。", stage="training")
    return path


def _optional_path(value: Any, field_name: str) -> Optional[Path]:
    if value is None:
        return None
    return _as_path(value, field_name)


def _validate_checkpoint_file(path: Path, allowed_roots: Sequence[Path]) -> Path:
    resolved = path.expanduser().resolve()
    if not _is_allowed_path(resolved, allowed_roots):
        raise AppError("OUTPUT_INVALID", f"权重路径不在允许范围内：{resolved}", stage="packaging")
    if not resolved.exists() or not resolved.is_file():
        raise AppError("VOICE_WEIGHTS_MISSING", f"权重文件不存在：{resolved}", stage="packaging")
    if resolved.suffix.lower() not in {".ckpt", ".pth"}:
        raise AppError("VOICE_WEIGHTS_MISSING", f"权重扩展名非法：{resolved.suffix}", stage="packaging")
    stat = resolved.stat()
    if stat.st_size <= 0:
        raise AppError("VOICE_WEIGHTS_MISSING", f"权重文件为空：{resolved}", stage="packaging")
    if stat.st_mtime <= 0:
        raise AppError("VOICE_WEIGHTS_MISSING", f"权重修改时间无效：{resolved}", stage="packaging")
    sample = resolved.read_bytes()[:1024]
    if sample and _looks_like_text(sample):
        raise AppError("VOICE_WEIGHTS_MISSING", f"权重文件疑似文本占位：{resolved}", stage="packaging")
    return resolved


def _looks_like_text(sample: bytes) -> bool:
    if b"\x00" in sample:
        return False
    printable = sum(32 <= byte <= 126 or byte in {9, 10, 13} for byte in sample)
    return printable == len(sample)


def _archive_weight(source: Path, archive_root: Path, voice_id: str) -> Path:
    archive_dir = archive_root / voice_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / source.name
    if source.resolve() == target.resolve():
        return target
    shutil.copy2(source, target)
    return target


def _is_allowed_path(path: Path, allowed_roots: Sequence[Path]) -> bool:
    roots = [root.expanduser().resolve() for root in allowed_roots]
    for root in roots:
        if path == root:
            return True
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _write_json_index(index_path: Path, records: Iterable[VoiceProfile]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="voices-", suffix=".json", dir=index_path.parent)
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


class _TrainingPlan:
    def __init__(
        self,
        *,
        task_id: Optional[str] = None,
        display_name: Optional[str] = None,
        feature_name: Optional[str] = None,
        engine_profile: str = "local-gpt-sovits",
        gpt_command: Optional[List[str]] = None,
        gpt_cwd: Optional[Path] = None,
        gpt_outputs: Optional[List[Path]] = None,
        gpt_timeout: int = 3600,
        gpt_weight_path: Optional[Path] = None,
        sovits_command: Optional[List[str]] = None,
        sovits_cwd: Optional[Path] = None,
        sovits_outputs: Optional[List[Path]] = None,
        sovits_timeout: int = 3600,
        sovits_weight_path: Optional[Path] = None,
        archive_root: Optional[Path] = None,
        allowed_roots: Optional[List[Path]] = None,
        log_dir: Optional[Path] = None,
        task_index: Optional[Path] = None,
        voice_index: Optional[Path] = None,
        references: Optional[List[EmotionReference]] = None,
    ) -> None:
        self.task_id = task_id
        self.display_name = display_name
        self.feature_name = feature_name
        self.engine_profile = engine_profile
        self.gpt_command = gpt_command
        self.gpt_cwd = gpt_cwd
        self.gpt_outputs = gpt_outputs or []
        self.gpt_timeout = gpt_timeout
        self.gpt_weight_path = gpt_weight_path or (self.gpt_outputs[0] if self.gpt_outputs else None)
        self.sovits_command = sovits_command
        self.sovits_cwd = sovits_cwd or gpt_cwd
        self.sovits_outputs = sovits_outputs or []
        self.sovits_timeout = sovits_timeout
        self.sovits_weight_path = sovits_weight_path or (self.sovits_outputs[0] if self.sovits_outputs else None)
        self.archive_root = archive_root or VOICE_ARCHIVE_ROOT
        self.allowed_roots = allowed_roots or []
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self.task_index = task_index or TASK_INDEX
        self.voice_index = voice_index or VOICE_INDEX
        self.references = references or []


__all__ = [
    "VOICE_INDEX",
    "get_voice",
    "get_voice_profile",
    "list_voices",
    "list_voice_profiles",
    "train_voice",
    "upsert_voice_profile",
]
