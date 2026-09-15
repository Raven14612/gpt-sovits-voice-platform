from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from adapters import GPTSoVITSAdapter
from models.schemas import AppError, TaskRecord, TaskStatus
from services import dataset_service, task_service
from services.audio_service import _audio_bounds, _inside, _load_config
from services.engine_service import LOCAL_CONFIG
from services.pipeline_service import PipelineRunner

from services.project_paths import PROJECT_ROOT


def feature_status(dataset_id):
    if not dataset_id:
        return "请先选择数据集。"
    record = dataset_service.get_dataset(dataset_id) if dataset_id else None
    if not record:
        return "所选数据集已不存在，请刷新列表后重新选择。"
    if record.status != "reviewed":
        return "请先在「音频数据处理」完成文本校对和情绪标签确认，并保存校对。"
    if not record.feature_manifest:
        return "校对已保存，尚未提取特征。请点击「准备训练数据（提取特征）」。"
    return f"已记录特征，训练前会校验完整性及校对版本。\n特征清单：{dataset_service.relative_path(record.feature_manifest)}"


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _nonempty(paths):
    for path in paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise AppError("FEATURE_EXTRACTION_FAILED", f"特征输出缺失或为空：{path.name}")


def _table(path, names, columns):
    rows = [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if (len(rows) != len(names) or any(len(row) != columns or any(not field.strip() for field in row) for row in rows)
            or {row[0] for row in rows} != set(names)):
        raise AppError("FEATURE_EXTRACTION_FAILED", f"{path.name} 与全部切片不一一对应。")
    return rows


def extract_features(dataset_id, *, task_id=None, config_path=LOCAL_CONFIG,
                     dataset_index=dataset_service.DATASET_INDEX, task_index=task_service.TASK_INDEX,
                     timeout=3600, task_kind="extract_features"):
    """Extract reviewed data only. This function never starts GPT/SoVITS training."""
    task_id = task_id or "features-" + uuid4().hex
    import re
    if not re.fullmatch(r"features-[a-zA-Z0-9-]{1,100}", task_id) or task_service.get_task(task_id, task_index):
        raise AppError("INVALID_TASK_ID", "特征任务 ID 无效或已存在。")
    task_service.try_acquire_gpu()
    current = None
    try:
        current = task_service.transition(TaskRecord(task_id=task_id, kind=task_kind,
                                          input_params={"dataset_id": dataset_id}),
                                          TaskStatus.RUNNING, stage="validating", message="校验已校对数据集")
        task_service.upsert_task(current, task_index)
        record = dataset_service.get_dataset(dataset_id, dataset_index)
        if record is None or record.status != "reviewed":
            raise AppError("DATASET_NOT_READY", "请先确认文本并保存校对，再提取特征。")
        data_root = PROJECT_ROOT / "data/datasets"
        if any(path is None or not _inside(path, data_root) for path in
               (record.source_path, record.slice_dir, record.list_path)):
            raise AppError("INVALID_AUDIO", "特征输入必须位于项目数据集目录。")
        wavs = sorted(record.slice_dir.glob("*.wav"))
        if not wavs:
            raise AppError("INVALID_AUDIO", "数据集没有切片。")
        # The transcript may live in a separate reviewed revision directory.
        rows = dataset_service._read_transcript(record.list_path)
        if len(rows) != len(wavs) or {Path(row[0]).resolve() for row in rows} != {p.resolve() for p in wavs}:
            raise AppError("TRANSCRIPT_INVALID", "校对标注与全部切片不一一对应。")
        for path in wavs:
            if not _inside(path, record.slice_dir):
                raise AppError("INVALID_AUDIO", "切片路径越界。")
            _audio_bounds(path, 0, None)
        names = [path.name for path in wavs]
        if len(set(names)) != len(names):
            raise AppError("INVALID_AUDIO", "切片文件名重复。")
        work = record.source_path.parent / "features" / task_id
        if not _inside(work, data_root):
            raise AppError("OUTPUT_INVALID", "特征目录越界。")
        work.mkdir(parents=True, exist_ok=False)
        snapshot = {str(p.resolve()): fingerprint(p) for p in [record.list_path, *wavs]}
        transcript = work / "input.list"
        transcript.write_text("\n".join("|".join(row) for row in rows) + "\n", encoding="utf-8")
        config = _load_config(config_path)
        adapter = GPTSoVITSAdapter(config)
        env = adapter.feature_environment(transcript, record.slice_dir, work)
        (work / "parameters.json").write_text(json.dumps({key: env[key] for key in
            ("inp_text", "inp_wav_dir", "opt_dir", "exp_name", "i_part", "all_parts", "_CUDA_VISIBLE_DEVICES",
             "is_half", "version", "bert_pretrained_dir", "cnhubert_base_dir", "sv_path", "pretrained_s2G", "s2config_path")
            if key in env}, ensure_ascii=False, indent=2), encoding="utf-8")
        commands = {stage: adapter.feature_command(stage) for stage in
                    ("feature_text", "feature_hubert", "feature_sv", "feature_semantic")}
        log_dir = PROJECT_ROOT / "data/logs/features"
        runner = PipelineRunner(log_dir)
        outputs = {
            "feature_text": [work / "2-name2text-0.txt", *[work / "3-bert" / (n + ".pt") for n in names]],
            "feature_hubert": [*[work / "4-cnhubert" / (n + ".pt") for n in names],
                               *[work / "5-wav32k" / n for n in names]],
            "feature_sv": [work / "7-sv_cn" / (n + ".pt") for n in names],
            "feature_semantic": [work / "6-name2semantic-0.tsv"],
        }
        for stage, command in commands.items():
            current = task_service.transition(current, TaskStatus.RUNNING, stage=stage,
                                              message=f"提取 {len(names)} 个切片的特征",
                                              log_path=log_dir / f"{task_id}-{stage}.log")
            task_service.upsert_task(current, task_index)
            current = runner.run_stage(current, stage, command, cwd=config.engine_root.resolve(),
                                       outputs=outputs[stage], env=env, timeout=timeout, gpu=False, final=False)
            task_service.upsert_task(current, task_index)
            if current.status != TaskStatus.RUNNING:
                return current
            _nonempty(outputs[stage])
            if stage == "feature_text":
                _table(work / "2-name2text-0.txt", names, 4)
                (work / "2-name2text.txt").write_bytes((work / "2-name2text-0.txt").read_bytes())
            elif stage == "feature_hubert":
                for name in names:
                    _audio_bounds(work / "5-wav32k" / name, 0, None)
            elif stage == "feature_semantic":
                semantic = _table(work / "6-name2semantic-0.tsv", names, 2)
                if any(not all(token.isdigit() for token in row[1].split()) for row in semantic):
                    raise AppError("FEATURE_EXTRACTION_FAILED", "语义 token 格式不合法。")
                (work / "6-name2semantic.tsv").write_text("item_name\tsemantic_audio\n" +
                    "\n".join("\t".join(row) for row in semantic) + "\n", encoding="utf-8")
        if any(fingerprint(Path(path)) != value for path, value in snapshot.items()):
            raise AppError("DATASET_CHANGED", "处理期间输入文件已改变，请重新提取。")
        manifest = work / "manifest.json"
        manifest.write_text(json.dumps({"dataset_id": dataset_id, "task_id": task_id,
            "engine_profile": config.profile, "version": "v2Pro", "slices": len(names),
            "inputs_sha256": {dataset_service.relative_path(Path(p)): digest for p, digest in snapshot.items()},
            "feature_dir": dataset_service.relative_path(work), "training_started": False,
            "outputs": [{"path": dataset_service.relative_path(p), "bytes": p.stat().st_size} for paths in outputs.values() for p in paths]
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        dataset_service.attach_features(record, manifest, dataset_index)
        current = task_service.transition(current, TaskStatus.SUCCEEDED,
            message=f"{len(names)} 个切片的 BERT、HuBERT、SV 和语义特征已完成；尚未训练。")
        task_service.upsert_task(current, task_index)
        return current
    except Exception as exc:
        if current is None:
            raise
        message = f"{exc.code}：{exc.message}" if isinstance(exc, AppError) else str(exc)
        if current.log_path and current.log_path.is_file():
            with current.log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\nSERVICE CHECK: {message}\n")
        failed = task_service.transition(current, TaskStatus.FAILED, message=message)
        task_service.upsert_task(failed, task_index)
        return failed
    finally:
        task_service.release_gpu()


def train_features(dataset_id, **kwargs):
    """Run the reviewed-data feature-training/preparation phase.

    The external GPT-SoVITS scripts call this phase feature extraction; the
    project-level contract names the deliverable ``train_features`` so it is
    distinct from model training and can be resumed/audited independently.
    """
    return extract_features(dataset_id, task_kind="train_features", **kwargs)
