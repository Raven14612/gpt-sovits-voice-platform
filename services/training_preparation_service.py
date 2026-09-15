"""Prepare reviewable v2Pro training configs without starting any subprocess."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import yaml

from models.schemas import AppError, DatasetRecord, EmotionReference
from services import dataset_service
from services.audio_service import _inside, _load_config
from services.engine_service import LOCAL_CONFIG
from services.feature_service import fingerprint
from services.voice_service import _validate_voice_id
from services.project_paths import PROJECT_ROOT, resolve_project_path
from services.path_migration import convert_fields, atomic_write
from services.storage_lock import serialized



@serialized
def prepare_training(dataset_id, voice_id, *, config_path=LOCAL_CONFIG,
                     dataset_index=dataset_service.DATASET_INDEX):
    from services.asset_service import ensure_ready
    ensure_ready(PROJECT_ROOT)
    _validate_voice_id(voice_id)
    record = dataset_service.get_dataset(dataset_id, dataset_index)
    if not record or record.status != "reviewed" or not record.feature_manifest:
        raise AppError("DATASET_NOT_READY", "请先完成校对和特征提取。")
    from services.asset_service import read_json, clone_dataset
    voices = read_json(PROJECT_ROOT / "data/index/voices.json")
    if any(v["voice_id"] == voice_id for v in voices):
        raise AppError("VOICE_EXISTS", "音色组 ID 已存在，请创建新的音色组。")
    owned = any(v["dataset_id"] == dataset_id for v in voices)
    for previous in (PROJECT_ROOT / "data/training").glob("*/plan.json"):
        saved = read_json(previous, {})
        owner = read_json(previous.parent / "ownership.json", saved)
        if owner.get("dataset_id") == dataset_id and owner.get("voice_id") != voice_id:
            owned = True
    data_root = PROJECT_ROOT / "data/datasets"
    manifest_path = record.feature_manifest.resolve()
    if not _inside(manifest_path, data_root):
        raise AppError("OUTPUT_INVALID", "特征清单路径越界。")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["dataset_id"] != dataset_id or manifest["version"] != "v2Pro":
        raise AppError("FEATURE_EXTRACTION_FAILED", "特征数据集或版本不匹配。")
    # Manifest paths are project-relative; never infer the root from directory depth.
    hashes = {str(resolve_project_path(name, root=PROJECT_ROOT)): digest
              for name, digest in manifest["inputs_sha256"].items()}
    if not record.list_path or str(record.list_path.resolve()) not in hashes:
        raise AppError("DATASET_CHANGED", "特征不属于当前校对版本。")
    for name, digest in hashes.items():
        path = Path(name)
        if not _inside(path, data_root) or not path.is_file() or fingerprint(path) != digest:
            raise AppError("DATASET_CHANGED", "特征输入已变化，请重新提取。")
    feature_dir = manifest_path.parent
    for item in manifest["outputs"]:
        path = resolve_project_path(item["path"], root=PROJECT_ROOT)
        if not _inside(path, feature_dir) or not path.is_file() or path.stat().st_size != item["bytes"]:
            raise AppError("FEATURE_EXTRACTION_FAILED", "特征文件缺失或大小变化。")
    if owned:
        record, _ = clone_dataset(dataset_id, root=PROJECT_ROOT)
        dataset_id = record.dataset_id
        manifest_path = record.feature_manifest.resolve()
        feature_dir = manifest_path.parent
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config = _load_config(config_path)
    root = config.engine_root.resolve()
    s2 = json.loads((root / "GPT_SoVITS/configs/s2v2Pro.json").read_text(encoding="utf-8"))
    s1 = yaml.safe_load((root / "GPT_SoVITS/configs/s1longer-v2.yaml").read_text(encoding="utf-8"))
    s2g = root / "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth"
    s2d = root / "GPT_SoVITS/pretrained_models/v2Pro/s2Dv2Pro.pth"
    s1base = root / "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt"
    for path in (s2g, s2d, s1base, config.python_path, root / "GPT_SoVITS/s1_train.py", root / "GPT_SoVITS/s2_train.py"):
        if not path.is_file():
            raise AppError("ENGINE_UNAVAILABLE", f"训练依赖缺失：{path.name}")
    run = PROJECT_ROOT / "data/training" / (voice_id + "-" + uuid4().hex)
    if not _inside(run, PROJECT_ROOT / "data/training"):
        raise AppError("OUTPUT_INVALID", "训练准备目录越界。")
    run.mkdir(parents=True, exist_ok=False)
    from services.asset_service import atomic_json
    atomic_json(run / "ownership.json", {"dataset_id": dataset_id, "voice_id": voice_id})
    # Training writes its own logs/config.json; preserve the accepted feature revision.
    work = run / "experiment"
    work.mkdir()
    for name in ("2-name2text.txt", "6-name2semantic.tsv", "3-bert", "4-cnhubert", "5-wav32k", "7-sv_cn"):
        source = feature_dir / name
        if source.is_dir():
            if any(not _inside(path, feature_dir) for path in source.rglob("*")):
                raise AppError("OUTPUT_INVALID", "特征目录包含越界链接。")
            shutil.copytree(source, work / name)
        else:
            if not _inside(source, feature_dir):
                raise AppError("OUTPUT_INVALID", "特征文件路径越界。")
            shutil.copy2(source, work / name)
    gpt_weights, sovits_weights = run / "GPT_weights", run / "SoVITS_weights"
    gpt_weights.mkdir()
    sovits_weights.mkdir()
    s2["train"].update(batch_size=4, epochs=8, text_low_lr_rate=0.4, fp16_run=True,
        pretrained_s2G=str(s2g), pretrained_s2D=str(s2d), if_save_latest=True,
        if_save_every_weights=True, save_every_epoch=4, gpu_numbers="0", grad_ckpt=False, lora_rank="32")
    s2["model"]["version"] = "v2Pro"
    s2["data"]["exp_dir"] = str(work)
    s2.update(s2_ckpt_dir=str(work), save_weight_dir=str(sovits_weights), name=voice_id, version="v2Pro")
    s1["train"].update(batch_size=4, epochs=15, save_every_n_epoch=5, precision="16-mixed",
        if_dpo=False, if_save_latest=True, if_save_every_weights=True,
        half_weights_save_dir=str(gpt_weights), exp_name=voice_id)
    s1.update(pretrained_s1=str(s1base), train_semantic_path=str(work / "6-name2semantic.tsv"),
        train_phoneme_path=str(work / "2-name2text.txt"), output_dir=str(work / "logs_s1_v2Pro"))
    s2path, s1path = run / "s2.json", run / "s1.yaml"
    s2path.write_text(json.dumps(s2, ensure_ascii=False, indent=2), encoding="utf-8")
    s1path.write_text(yaml.safe_dump(s1, allow_unicode=True), encoding="utf-8")
    plan = {"dataset_id": dataset_id, "voice_id": voice_id, "status": "prepared_not_executed",
        "feature_manifest": dataset_service.relative_path(manifest_path), "slices": manifest["slices"],
        "cwd": "<engine_root>", "environment": {"version": "v2Pro", "_CUDA_VISIBLE_DEVICES": "0",
        "CUDA_VISIBLE_DEVICES": "0", "hz": "25hz", "PYTHONIOENCODING": "utf-8"},
        "stages": [
            {"stage": "train_gpt", "command": ["<python_path>", "-s", "GPT_SoVITS/s1_train.py", "--config_file", dataset_service.relative_path(s1path)],
             "expected_weights": dataset_service.relative_path(gpt_weights) + "/" + voice_id + "-e15.ckpt"},
            {"stage": "train_sovits", "command": ["<python_path>", "-s", "GPT_SoVITS/s2_train.py", "--config", dataset_service.relative_path(s2path)],
             "expected_weights": dataset_service.relative_path(sovits_weights) + "/" + voice_id + "_e8_s*.pth"}],
        "training_started": False}
    target = run / "plan.json"
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def materialize_training_configs(run: Path):
    run = resolve_project_path(run, root=PROJECT_ROOT)
    if not _inside(run, PROJECT_ROOT / "data/training"):
        raise AppError("OUTPUT_INVALID", "训练配置目录越界。", stage="training")
    # Resolve a moved preparation into new runtime configs; keep original evidence intact.
    s1 = yaml.safe_load((run / "s1.yaml").read_text(encoding="utf-8"))
    s2 = json.loads((run / "s2.json").read_text(encoding="utf-8"))
    def runtime_path(value):
        path = resolve_project_path(value, root=PROJECT_ROOT)
        if not _inside(path, PROJECT_ROOT):
            raise AppError("OUTPUT_INVALID", "训练配置仍包含项目外路径，请补充迁移映射。", stage="training")
        return path
    s1 = convert_fields(s1, runtime_path)
    s2 = convert_fields(s2, runtime_path)
    s1path, s2path = run / "runtime-s1.yaml", run / "runtime-s2.json"
    atomic_write(s1path, yaml.safe_dump(s1, allow_unicode=True).encode("utf-8"))
    atomic_write(s2path, json.dumps(s2, ensure_ascii=False, indent=2).encode("utf-8"))
    return s1path, s2path


@serialized
def training_parameters(plan_path: Path, dataset: DatasetRecord, display_name: str,
                        task_id: str, *, config_path=LOCAL_CONFIG) -> dict:
    """Turn a reviewed preparation plan into explicit subprocess parameters."""
    plan_path = resolve_project_path(plan_path, root=PROJECT_ROOT)
    training_root = (PROJECT_ROOT / "data" / "training").resolve()
    if not _inside(plan_path, training_root) or plan_path.name != "plan.json":
        raise AppError("OUTPUT_INVALID", "训练计划路径越界。", stage="training")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("status") != "prepared_not_executed":
        raise AppError("DATASET_CHANGED", "历史训练计划不能重放，请重新准备训练。", stage="training")
    if plan.get("dataset_id") != dataset.dataset_id or plan.get("voice_id") is None:
        raise AppError("DATASET_CHANGED", "训练计划与数据集不匹配。", stage="training")
    voice_id = str(plan["voice_id"])
    run = plan_path.parent
    config = _load_config(config_path)
    root = config.engine_root.resolve()
    s1path, s2path = materialize_training_configs(run)
    gpt_weight = run / "GPT_weights" / f"{voice_id}-e15.ckpt"
    sovits_glob = run / "SoVITS_weights" / f"{voice_id}_e8_s*.pth"
    references = _training_references(dataset)
    plan.update(status="running", training_started=True, task_id=task_id)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "task_id": task_id,
        "display_name": display_name,
        "feature_name": voice_id,
        "engine_profile": config.profile,
        "gpt_command": [str(config.python_path.resolve()), "-s", "GPT_SoVITS/s1_train.py",
                        "--config_file", str(s1path)],
        "gpt_cwd": root,
        "gpt_outputs": [gpt_weight],
        "gpt_weight_path": gpt_weight,
        "gpt_timeout": 7200,
        "sovits_command": [str(config.python_path.resolve()), "-s", "GPT_SoVITS/s2_train.py",
                           "--config", str(s2path)],
        "sovits_cwd": root,
        "sovits_outputs": [],
        "sovits_weight_glob": str(sovits_glob),
        "sovits_timeout": 7200,
        "allowed_roots": [run],
        "references": references,
    }


def finish_training_plan(plan_path: Path, task) -> None:
    plan_path = Path(plan_path).resolve()
    if not _inside(plan_path, (PROJECT_ROOT / "data" / "training").resolve()):
        raise AppError("OUTPUT_INVALID", "训练计划路径越界。", stage="training")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["training_started"] = True
    plan["status"] = "succeeded" if task.status.value == "succeeded" else "failed"
    plan["task_id"] = task.task_id
    plan["final_stage"] = task.stage
    plan["message"] = task.message
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def fail_training_plan(plan_path: Path, task_id: str, message: str) -> None:
    plan_path = Path(plan_path).resolve()
    if not _inside(plan_path, (PROJECT_ROOT / "data" / "training").resolve()):
        return
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan.update(training_started=True, status="failed", task_id=task_id,
                final_stage="training", message=message)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def _training_references(dataset: DatasetRecord):
    if not dataset.list_path or not dataset.emotions_path or not dataset.slice_dir:
        raise AppError("REFERENCE_MISSING", "数据集缺少校对文本、情绪或切片。", stage="training")
    rows = dataset_service._read_transcript(dataset.list_path)
    emotions = json.loads(dataset.emotions_path.read_text(encoding="utf-8"))
    by_name = {Path(name).name: emotion for name, emotion in emotions.items()}
    references = []
    seen = set()
    for row in rows:
        if len(row) < 4:
            continue
        name = Path(row[0]).name
        emotion = by_name.get(name)
        audio = dataset.slice_dir / name
        if emotion in {"neutral", "happy", "sad"} and emotion not in seen and audio.is_file():
            references.append(EmotionReference(
                emotion=emotion, audio_path=audio.resolve(), prompt_text=row[3], language="zh"
            ))
            seen.add(emotion)
    if not references:
        raise AppError("REFERENCE_MISSING", "没有可用于合成验证的已标注参考切片。", stage="training")
    return references
