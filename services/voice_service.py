from __future__ import annotations

import hashlib
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
from services.project_paths import PROJECT_ROOT, resolve_project_path
from services.storage_lock import serialized

VOICE_INDEX = PROJECT_ROOT / "data" / "index" / "voices.json"
VOICE_ARCHIVE_ROOT = PROJECT_ROOT / "data" / "voices"
DEFAULT_LOG_DIR = PROJECT_ROOT / "data" / "logs" / "training"

def _runtime_profile(record: VoiceProfile) -> VoiceProfile:
    values = {}
    for key in ("gpt_weight", "sovits_weight"):
        value = getattr(record, key)
        if value:
            values[key] = resolve_project_path(value, root=PROJECT_ROOT)
    refs = [item.model_copy(update={"audio_path": resolve_project_path(item.audio_path, root=PROJECT_ROOT)})
            for item in record.references]
    values["references"] = refs
    return record.model_copy(update=values)

def _stored_profile(record: VoiceProfile) -> dict:
    data = record.model_dump(mode="json")
    for key in ("gpt_weight", "sovits_weight"):
        if data.get(key):
            try: data[key] = Path(data[key]).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
            except ValueError: data[key] = Path(data[key]).as_posix()
    for ref in data.get("references", []):
        try: ref["audio_path"] = Path(ref["audio_path"]).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
        except ValueError: ref["audio_path"] = Path(ref["audio_path"]).as_posix()
    return data


def list_voice_profiles(index_path: Path = VOICE_INDEX) -> List[VoiceProfile]:
    if not index_path.is_file():
        return []
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
        return [_runtime_profile(VoiceProfile.model_validate(item)) for item in raw] if isinstance(raw, list) else []
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def get_voice_profile(voice_id: str, index_path: Path = VOICE_INDEX) -> Optional[VoiceProfile]:
    return next((item for item in list_voice_profiles(index_path) if item.voice_id == voice_id), None)


@serialized
def upsert_voice_profile(record: VoiceProfile, index_path: Path = VOICE_INDEX) -> VoiceProfile:
    from services.asset_service import ensure_ready
    ensure_ready(_asset_root(index_path))
    records = [item for item in list_voice_profiles(index_path) if item.voice_id != record.voice_id]
    records.append(record)
    _write_json_index(index_path, records)
    return record


def list_voices(index_path: Path = VOICE_INDEX) -> List[VoiceProfile]:
    return list_voice_profiles(index_path)


def get_voice(voice_id: str, index_path: Path = VOICE_INDEX) -> Optional[VoiceProfile]:
    return get_voice_profile(voice_id, index_path)


def _read_voice_data(index_path: Path) -> list[dict]:
    try:
        records = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError("voice index must be a list")
        profiles = [VoiceProfile.model_validate(item) for item in records]
        if len({item.voice_id for item in profiles}) != len(profiles):
            raise ValueError("duplicate voice ids")
        return records
    except (OSError, ValueError) as exc:
        raise AppError("VOICE_INDEX_INVALID", "音色索引无法读取，原文件已保留。") from exc


def _deleted_record(records, voice_id):
    record = next((item for item in records if item["voice_id"] == voice_id), None)
    if record is None:
        raise AppError("VOICE_MISSING", "音色已不存在，请刷新列表。")
    if record.get("status") != "deleted":
        raise AppError("VOICE_STATE_INVALID", "只能彻底删除「已删除音色」中的项目。")
    return record


def _voice_fingerprint(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _asset_root(index_path):
    path = Path(index_path).resolve()
    if path == VOICE_INDEX.resolve():
        return PROJECT_ROOT
    if path.parent.name == "index" and path.parent.parent.name == "data":
        return path.parents[2]
    return path.parent


@serialized
def prepare_voice_purge(voice_id: str, index_path: Path = VOICE_INDEX) -> dict:
    from services.asset_service import deletion_plan, ensure_ready
    _validate_voice_id(voice_id)
    _read_voice_data(index_path)
    ensure_ready(_asset_root(index_path))
    return deletion_plan(voice_id, index_path, _asset_root(index_path))


def purge_voice(voice_id: str, fingerprint: str, index_path: Path = VOICE_INDEX) -> None:
    from services.asset_service import execute_delete
    from services.storage_lock import metadata_lock
    from services import history_service
    _validate_voice_id(voice_id)
    try_acquire_gpu()
    try:
        with metadata_lock():
            pending = prepare_voice_purge(voice_id, index_path)
            if pending["fingerprint"] != fingerprint:
                raise AppError("VOICE_CHANGED", "音色组或关联材料已变化，请重新确认。")
            if Path(index_path).resolve() == VOICE_INDEX.resolve():
                history_service.backfill_snapshots()
            execute_delete(pending, index_path, _asset_root(index_path))
    finally:
        release_gpu()


@serialized
def set_voice_deleted(voice_id: str, deleted: bool, index_path: Path = VOICE_INDEX) -> None:
    """Remove/restore a library entry without deleting weights or historical audio."""
    _validate_voice_id(voice_id)
    from services.asset_service import ensure_ready
    ensure_ready(_asset_root(index_path))
    # Training and synthesis share this process-wide/file lock. Library writes
    # must not race training's index publication or a running model task.
    try_acquire_gpu()
    try:
        records = _read_voice_data(index_path)
        record = next((item for item in records if item["voice_id"] == voice_id), None)
        if record is None:
            raise AppError("VOICE_MISSING", "音色已不存在，请刷新列表。")
        target = "deleted" if deleted else "verified"
        if record.get("status", "draft") == target:
            return
        expected = "verified" if deleted else "deleted"
        if record.get("status", "draft") != expected:
            raise AppError("VOICE_STATE_INVALID", "当前音色状态不支持此操作。")
        if not deleted:
            profile = _runtime_profile(VoiceProfile.model_validate(record))
            if any(path is None or not path.is_file() for path in (profile.gpt_weight, profile.sovits_weight)):
                raise AppError("VOICE_WEIGHTS_MISSING", "模型权重缺失，暂时无法恢复音色。")
            if any(not ref.audio_path.is_file() for ref in profile.references):
                raise AppError("REFERENCE_MISSING", "参考音频缺失，暂时无法恢复音色组。")
        record["status"] = target
        _write_voice_data(index_path, records)
    finally:
        release_gpu()


def train_voice(
    dataset: Union[DatasetRecord, Mapping[str, Any]],
    voice_id: str,
    params: Mapping[str, Any],
) -> TaskRecord:
    _validate_voice_id(voice_id)
    plan = _parse_training_params(params)
    if plan.gpt_command is None or plan.sovits_command is None:
        raise AppError("NOT_IMPLEMENTED", "训练引擎尚未接入，缺少 GPT/SoVITS stage command。", stage="training")

    _archive_target(Path("gpt.ckpt"), plan.archive_root, voice_id)
    _archive_target(Path("sovits.pth"), plan.archive_root, voice_id)
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
        try:
            gpt_before = _checkpoint_state(plan.gpt_weight_path, plan.gpt_weight_glob, plan.allowed_roots)
        except (AppError, OSError) as exc:
            failed = transition(current, TaskStatus.FAILED, message=str(exc))
            upsert_task(failed, plan.task_index)
            return failed
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
        try:
            sovits_before = _checkpoint_state(plan.sovits_weight_path, plan.sovits_weight_glob, plan.allowed_roots)
        except (AppError, OSError) as exc:
            failed = transition(current, TaskStatus.FAILED, message=str(exc))
            upsert_task(failed, plan.task_index)
            return failed
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
            gpt_weight = _resolve_checkpoint(
                plan.gpt_weight_path, plan.gpt_weight_glob, plan.allowed_roots, gpt_before
            )
            sovits_weight = _resolve_checkpoint(
                plan.sovits_weight_path, plan.sovits_weight_glob, plan.allowed_roots, sovits_before
            )
            archived_gpt = _archive_weight(gpt_weight, plan.archive_root, voice_id)
            archived_sovits = _archive_weight(sovits_weight, plan.archive_root, voice_id)

            from services.history_service import file_hash
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
                weight_hashes={"gpt_weight": file_hash(archived_gpt),
                               "sovits_weight": file_hash(archived_sovits)},
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
    gpt_weight_glob = _optional_checkpoint_glob(params.get("gpt_weight_glob"), "gpt_weight_glob")
    if not gpt_outputs and params.get("gpt_weight_path") is None and gpt_weight_glob is None:
        raise AppError("NOT_IMPLEMENTED", "训练引擎尚未接入，缺少 GPT stage output path。", stage="train_gpt")
    gpt_weight_path = (_as_path(params.get("gpt_weight_path", gpt_outputs[0] if gpt_outputs else None),
                                "gpt_weight_path")
                       if gpt_outputs or params.get("gpt_weight_path") is not None else None)

    allowed_roots = _as_paths(params.get("allowed_roots", []), "allowed_roots")
    archive_root = _as_path(params.get("archive_root", VOICE_ARCHIVE_ROOT), "archive_root")
    allowed_roots = [archive_root, gpt_cwd, *allowed_roots]

    sovits_command = _as_command(params.get("sovits_command"))
    sovits_cwd = _as_path(params.get("sovits_cwd", gpt_cwd), "sovits_cwd")
    sovits_outputs = _as_paths(params.get("sovits_outputs", []), "sovits_outputs")
    sovits_weight_glob = _optional_checkpoint_glob(params.get("sovits_weight_glob"), "sovits_weight_glob")
    if (sovits_command is not None and not sovits_outputs
            and params.get("sovits_weight_path") is None and sovits_weight_glob is None):
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
        gpt_weight_glob=gpt_weight_glob,
        sovits_command=sovits_command,
        sovits_cwd=sovits_cwd,
        sovits_outputs=sovits_outputs,
        sovits_timeout=int(params.get("sovits_timeout", params.get("timeout", 3600))),
        sovits_weight_path=sovits_weight_path,
        sovits_weight_glob=sovits_weight_glob,
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


def _optional_checkpoint_glob(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    raw = str(value)
    candidate = Path(raw)
    if any(char in str(candidate.parent) for char in "*?[]") or not any(char in candidate.name for char in "*?["):
        raise AppError("OUTPUT_INVALID", f"{field_name} 必须只在文件名中包含通配符。", stage="training")
    return str(candidate.parent.expanduser().resolve() / candidate.name)


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
    with resolved.open("rb") as handle:
        sample = handle.read(1024)
    if sample and _looks_like_text(sample):
        raise AppError("VOICE_WEIGHTS_MISSING", f"权重文件疑似文本占位：{resolved}", stage="packaging")
    return resolved


def _looks_like_text(sample: bytes) -> bool:
    if b"\x00" in sample:
        return False
    printable = sum(32 <= byte <= 126 or byte in {9, 10, 13} for byte in sample)
    return printable == len(sample)


def _archive_weight(source: Path, archive_root: Path, voice_id: str) -> Path:
    target = _archive_target(source, archive_root, voice_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _archive_target(source, archive_root, voice_id)
    if source.resolve() == target.resolve():
        return target
    shutil.copy2(source, target)
    return target


def _validate_voice_id(voice_id: str) -> None:
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³")
    if (
        not isinstance(voice_id, str)
        or not voice_id
        or voice_id in {".", ".."}
        or voice_id != voice_id.strip()
        or voice_id.endswith(".")
        or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in voice_id)
        or voice_id.split(".")[0].upper() in reserved
    ):
        raise AppError("INVALID_VOICE_ID", "音色 ID 必须是有效的单层目录名。", stage="training")


def _archive_target(source: Path, archive_root: Path, voice_id: str) -> Path:
    _validate_voice_id(voice_id)
    root = archive_root.expanduser().resolve()
    archive_dir = (root / voice_id).resolve()
    target = (archive_dir / source.name).resolve()
    if archive_dir == root or not _is_allowed_path(archive_dir, [root]) or not _is_allowed_path(target, [archive_dir]):
        raise AppError("OUTPUT_INVALID", "音色归档路径超出允许目录。", stage="packaging")
    return target


def _checkpoint_snapshot(path: Path, allowed_roots: Sequence[Path]) -> Optional[str]:
    resolved = path.expanduser().resolve()
    if not _is_allowed_path(resolved, allowed_roots):
        raise AppError("OUTPUT_INVALID", f"权重路径不在允许范围内：{resolved}", stage="packaging")
    if not resolved.exists():
        return None
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_checkpoint_change(path: Path, allowed_roots: Sequence[Path], before: Optional[str]) -> None:
    # Content comparison also catches unchanged weights with a refreshed timestamp.
    after = _checkpoint_snapshot(path, allowed_roots)
    if after is None or after == before:
        raise AppError("OUTPUT_STALE", f"本次训练未生成新的权重内容：{path}", stage="packaging")


def _checkpoint_state(path: Optional[Path], pattern: Optional[str],
                      allowed_roots: Sequence[Path]) -> dict:
    candidates = [path] if path is not None and path.exists() else []
    if pattern:
        parent, name = Path(pattern).parent.resolve(), Path(pattern).name
        if not _is_allowed_path(parent, allowed_roots):
            raise AppError("OUTPUT_INVALID", f"权重路径不在允许范围内：{parent}", stage="packaging")
        candidates.extend(item for item in parent.glob(name) if item.is_file())
    return {str(item.resolve()): _checkpoint_snapshot(item, allowed_roots) for item in candidates}


def _resolve_checkpoint(path: Optional[Path], pattern: Optional[str], allowed_roots: Sequence[Path],
                        before: Mapping[str, Optional[str]]) -> Path:
    if path is not None:
        candidate = _validate_checkpoint_file(path, allowed_roots)
        _require_checkpoint_change(candidate, allowed_roots, before.get(str(candidate.resolve())))
        return candidate
    if not pattern:
        raise AppError("VOICE_WEIGHTS_MISSING", "训练未配置权重输出。", stage="packaging")
    parent, name = Path(pattern).parent.resolve(), Path(pattern).name
    if not _is_allowed_path(parent, allowed_roots):
        raise AppError("OUTPUT_INVALID", f"权重路径不在允许范围内：{parent}", stage="packaging")
    changed = []
    for candidate in parent.glob(name):
        valid = _validate_checkpoint_file(candidate, allowed_roots)
        digest = _checkpoint_snapshot(valid, allowed_roots)
        if digest != before.get(str(valid.resolve())):
            changed.append(valid)
    if not changed:
        raise AppError("OUTPUT_STALE", f"本次训练未生成新的匹配权重：{pattern}", stage="packaging")
    return max(changed, key=lambda item: item.stat().st_mtime_ns)


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
    _write_voice_data(index_path, [_stored_profile(item) for item in records])


def _write_voice_data(index_path: Path, records: list[dict]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="voices-", suffix=".json", dir=index_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
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
        gpt_weight_glob: Optional[str] = None,
        sovits_command: Optional[List[str]] = None,
        sovits_cwd: Optional[Path] = None,
        sovits_outputs: Optional[List[Path]] = None,
        sovits_timeout: int = 3600,
        sovits_weight_path: Optional[Path] = None,
        sovits_weight_glob: Optional[str] = None,
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
        self.gpt_weight_glob = gpt_weight_glob
        self.sovits_command = sovits_command
        self.sovits_cwd = sovits_cwd or gpt_cwd
        self.sovits_outputs = sovits_outputs or []
        self.sovits_timeout = sovits_timeout
        self.sovits_weight_path = sovits_weight_path or (self.sovits_outputs[0] if self.sovits_outputs else None)
        self.sovits_weight_glob = sovits_weight_glob
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
