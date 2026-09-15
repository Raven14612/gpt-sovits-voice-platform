"""Explicit ownership, independent dataset copies and recoverable physical deletion."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from uuid import uuid4

from models.schemas import AppError
from models.schemas import DatasetRecord, VoiceProfile
from services.project_paths import PROJECT_ROOT, resolve_project_path
from services.storage_lock import serialized


def read_json(path, default=None):
    if not path.exists():
        return [] if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AppError("OWNERSHIP_INVALID", f"无法读取文件归属：{path.name}") from exc


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix="metadata-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def validate_records(records, model, key):
    try:
        if not isinstance(records, list):
            raise ValueError("index is not a list")
        for record in records:
            model.model_validate(record)
        if len({r[key] for r in records}) != len(records):
            raise ValueError("duplicate identifiers")
    except (ValueError, KeyError, TypeError) as exc:
        raise AppError("OWNERSHIP_INVALID", "仓库索引无效或包含重复 ID，停止文件清理。") from exc


def checked(path, root, *, areas=("datasets", "training", "voices", "tmp/gradio")):
    """Validate the lexical path AND reparse points before resolving/removing."""
    root = root.resolve()
    raw = Path(os.path.abspath(path))
    allowed = [root / "data" / area for area in areas]
    if not any(raw != area and raw.is_relative_to(area) for area in allowed):
        raise AppError("DELETE_PATH_INVALID", f"清理路径不在独占材料目录内：{raw}")
    for part in [raw, *raw.parents]:
        if part == root:
            break
        if part.exists() or part.is_symlink():
            attrs = getattr(part.lstat(), "st_file_attributes", 0)
            if part.is_symlink() or attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise AppError("DELETE_PATH_INVALID", f"材料目录含链接，停止清理：{part}")
    if not any(raw.resolve() != area and raw.resolve().is_relative_to(area) for area in allowed):
        raise AppError("DELETE_PATH_INVALID", "清理路径越界。")
    return raw


def checked_tree(path, root, *, areas=("datasets", "training", "voices", "tmp/gradio")):
    checked(path, root, areas=areas)
    if path.is_dir():
        for directory, dirs, files in os.walk(path, followlinks=False):
            for name in dirs + files:
                checked(Path(directory) / name, root, areas=areas)


def dataset_roots(dataset, root):
    """Recognize historical sibling revisions by their complete slice references."""
    raw = Path(dataset["source_path"])
    if not raw.is_absolute() or raw.is_relative_to(root):
        checked(root / raw, root)
    base = resolve_project_path(dataset["source_path"], root=root).parent
    checked_tree(base, root)
    if base.parent != root / "data/datasets" or base.name != dataset["dataset_id"]:
        raise AppError("OWNERSHIP_INVALID", "数据集根目录不是独立目录。")
    roots = {base}
    for key in ("slice_dir", "list_path", "emotions_path", "feature_manifest"):
        if dataset.get(key):
            path = resolve_project_path(dataset[key], root=root)
            checked(path, root)
            rel = path.relative_to(root / "data/datasets")
            if len(rel.parts) < 2:
                raise AppError("OWNERSHIP_INVALID", "材料路径缺少独立目录。")
            roots.add(root / "data/datasets" / rel.parts[0])
    for transcript in (root / "data/datasets").glob("*/corrected.list"):
        if transcript.parent in roots:
            continue
        checked(transcript, root)
        try:
            rows = [line.split("|", 3) for line in transcript.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
            if rows and all(len(row) == 4 and resolve_project_path(row[0], root=root).is_relative_to(base) for row in rows):
                roots.add(transcript.parent)
        except (OSError, ValueError):
            continue  # Unprovable orphan: never infer ownership from its name.
    for path in roots:
        checked_tree(path, root)
        if path != base and path.exists():
            transcript = path / "corrected.list"
            if not transcript.is_file() or any(p.name not in {"corrected.list", "emotions.json", "revision.json"} for p in path.iterdir()):
                raise AppError("OWNERSHIP_INVALID", f"旧版本目录归属不明确：{path.name}")
            rows = [line.split("|", 3) for line in transcript.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
            if not rows or not all(len(row) == 4 and resolve_project_path(row[0], root=root).is_relative_to(base) for row in rows):
                raise AppError("OWNERSHIP_INVALID", f"旧版本含其他数据集引用：{path.name}")
    return roots


def inventory(roots, root):
    entries = []
    for path in sorted(roots):
        checked_tree(path, root)
        for file in sorted(path.rglob("*")) if path.is_dir() else [path]:
            if file.is_file():
                info = file.stat()
                entries.append([file.relative_to(root).as_posix(), info.st_size, info.st_mtime_ns])
    return entries


def deletion_plan(voice_id, index_path, root=PROJECT_ROOT):
    root = Path(root).resolve()
    voices = read_json(index_path)
    validate_records(voices, VoiceProfile, "voice_id")
    voice = next((v for v in voices if v["voice_id"] == voice_id), None)
    if not voice or voice.get("status") not in {"verified", "deleted"}:
        raise AppError("VOICE_STATE_INVALID", "请选择可用或已删除的音色组。")
    datasets = read_json(root / "data/index/datasets.json")
    validate_records(datasets, DatasetRecord, "dataset_id")
    dataset = next((d for d in datasets if d["dataset_id"] == voice["dataset_id"]), None)
    roots = set()
    if dataset:
        shared = [v for v in voices if v["voice_id"] != voice_id and v["dataset_id"] == dataset["dataset_id"]]
        if shared:
            raise AppError("ASSETS_SHARED", "旧音色组共用材料，请先执行仓库迁移后再删除。")
        roots |= dataset_roots(dataset, root)
        owner = read_json(resolve_project_path(dataset["source_path"], root=root).parent / "ownership.json", {})
        shared_caches = set()
        for other in datasets:
            if other["dataset_id"] != dataset["dataset_id"]:
                info = read_json(resolve_project_path(other["source_path"], root=root).parent / "ownership.json", {})
                shared_caches.update(info.get("upload_cache_files", []))
        for value in set(owner.get("upload_cache_files", [])) - shared_caches:
            path = checked(root / value, root, areas=("tmp/gradio",))
            if path.is_file():
                roots.add(path)
        runs = {p.parent for pattern in ("*/plan.json", "*/ownership.json") for p in (root / "data/training").glob(pattern)}
        for run in runs:
            checked(run, root)
            data = read_json(run / "ownership.json", read_json(run / "plan.json", {}))
            if data.get("dataset_id") == dataset["dataset_id"] or data.get("voice_id") == voice_id:
                roots.add(run)
    archive = root / "data/voices" / voice_id
    if archive.exists():
        roots.add(checked(archive, root))
    for key in ("gpt_weight", "sovits_weight"):
        if voice.get(key):
            raw = Path(voice[key])
            if not raw.is_absolute() or raw.is_relative_to(root):
                checked(root / raw, root)
            path = resolve_project_path(voice[key], root=root)
            if path.exists():
                if path.suffix.lower() not in {".pth", ".ckpt"}:
                    raise AppError("OWNERSHIP_INVALID", "音色权重路径不是权重文件。")
                roots.add(checked(path, root))
    # References outside the source root must still have known ownership.
    for ref in voice.get("references", []):
        path = resolve_project_path(ref["audio_path"], root=root)
        if path.exists() and not any(path == p or path.is_relative_to(p) for p in roots):
            raise AppError("OWNERSHIP_INVALID", "参考音频未归属于该音色组，需先迁移归属。")
    for other in datasets:
        if dataset and other["dataset_id"] == dataset["dataset_id"]:
            continue
        for key in ("source_path", "slice_dir", "list_path", "emotions_path", "feature_manifest"):
            if other.get(key):
                path = resolve_project_path(other[key], root=root)
                if any(path == p or path.is_relative_to(p) for p in roots):
                    raise AppError("ASSETS_SHARED", "材料仍被其他数据集使用，停止清理。")
    for other in voices:
        if other["voice_id"] == voice_id:
            continue
        paths = [other.get(k) for k in ("gpt_weight", "sovits_weight")]
        paths += [ref["audio_path"] for ref in other.get("references", [])]
        if any(value and any((p := resolve_project_path(value, root=root)) == r or p.is_relative_to(r) for r in roots) for value in paths):
            raise AppError("ASSETS_SHARED", "材料仍被其他音色组使用，停止清理。")
    roots = {p for p in roots if not any(p != q and p.is_relative_to(q) for q in roots)}
    entries = inventory(roots, root)
    plan = {"voice_id": voice_id, "display_name": voice["display_name"],
            "dataset_id": dataset["dataset_id"] if dataset else None,
            "paths": [p.relative_to(root).as_posix() for p in sorted(roots)],
            "files": len(entries), "bytes": sum(e[1] for e in entries)}
    content = json.dumps([voice, dataset, entries, plan["paths"]], sort_keys=True, ensure_ascii=False)
    plan["fingerprint"] = hashlib.sha256(content.encode()).hexdigest()
    return plan


def _transaction_root(root):
    return root / "data/deletions"


def ensure_ready(root=PROJECT_ROOT):
    for file in _transaction_root(root).glob("*/transaction.json"):
        if read_json(file, {}).get("phase") not in {"done", "rolled_back"}:
            raise AppError("DELETE_PENDING", "仓库有未完成的清理，请点击重试清理或重启应用。")


def _finish(file, root):
    tx = read_json(file, {})
    if tx["phase"] in {"done", "rolled_back"}:
        return
    if tx["phase"] not in {"staging", "committed"}:
        raise AppError("DELETE_RECOVERY_CONFLICT", "未知的删除事务状态，停止清理。")
    targets = []
    for entry in tx["moves"]:
        source = checked(root / entry["source"], root)
        target = checked(root / entry["target"], root, areas=("deletions",))
        checked_tree(target, root, areas=("deletions",))
        if not target.is_relative_to(file.parent / "files"):
            raise AppError("DELETE_PATH_INVALID", "删除事务暂存目录越界。")
        targets.append((source, target))
    if tx["phase"] == "staging":
        for source, target in reversed(targets):
            if target.exists():
                if source.exists():
                    raise AppError("DELETE_RECOVERY_CONFLICT", "原位置已出现新文件，停止恢复。")
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, source)
        tx["phase"] = "rolled_back"
        atomic_json(file, tx)
        return
    for name, key, value in (("voices.json", "voice_id", tx["voice_id"]),
                             ("datasets.json", "dataset_id", tx.get("dataset_id"))):
        index = Path(tx["voice_index"]) if name == "voices.json" else root / "data/index" / name
        if index.resolve() != (root / "data/index" / name).resolve() and index.resolve() != (root / name).resolve():
            raise AppError("DELETE_PATH_INVALID", "删除事务索引越界。")
        records = read_json(index)
        if value is not None and any(r[key] == value for r in records):
            atomic_json(index, [r for r in records if r[key] != value])
    for source, target in targets:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    ownership = root / "data/ownership" / (hashlib.sha256(tx["voice_id"].encode()).hexdigest() + ".json")
    ownership.unlink(missing_ok=True)
    # Keep only a small audit receipt, with no source text or model contents.
    tx["phase"] = "done"
    atomic_json(file, tx)


@serialized
def recover_deletions(root=PROJECT_ROOT):
    from services import task_service
    task_service.try_acquire_gpu(kind="recovery")
    try:
        recovered = []
        for file in _transaction_root(root).glob("*/transaction.json"):
            if read_json(file, {}).get("phase") not in {"done", "rolled_back"}:
                _finish(file, root)
                recovered.append(file.parent.name)
        return recovered
    finally:
        task_service.release_gpu()


@serialized
def execute_delete(plan, index_path, root=PROJECT_ROOT):
    ensure_ready(root)
    current = deletion_plan(plan["voice_id"], index_path, root)
    if current["fingerprint"] != plan["fingerprint"]:
        raise AppError("VOICE_CHANGED", "音色组或关联材料已变化，请重新查看删除范围并确认。")
    directory = _transaction_root(root) / uuid4().hex
    moves = [{"source": path, "target": (directory / "files" / str(i)).relative_to(root).as_posix()}
             for i, path in enumerate(current["paths"])]
    tx = {**current, "phase": "staging", "voice_index": str(index_path.resolve()), "moves": moves}
    file = directory / "transaction.json"
    atomic_json(file, tx)
    try:
        for entry in moves:
            source = checked(root / entry["source"], root)
            target = checked(root / entry["target"], root, areas=("deletions",))
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.exists():
                os.replace(source, target)
        tx["phase"] = "committed"
        atomic_json(file, tx)
    except OSError:
        _finish(file, root)  # Roll back before publication, preserving accepted data.
        raise
    try:
        _finish(file, root)
    except OSError as exc:
        raise AppError("DELETE_PENDING", "音色组正在清理；部分文件被占用，请释放后重试清理或重启。") from exc


@serialized
def clone_dataset(dataset_id, *, root=PROJECT_ROOT):
    """Copy all owned revisions/features; rewrite only operational copies and hashes."""
    from services import dataset_service
    from services.history_service import file_hash
    from models.schemas import DatasetRecord
    index = root / "data/index/datasets.json"
    records = read_json(index)
    original = next((d for d in records if d["dataset_id"] == dataset_id), None)
    if not original:
        raise AppError("DATASET_MISSING", "待复制数据集不存在。")
    roots = dataset_roots(original, root)
    new_id = uuid4().hex
    base = resolve_project_path(original["source_path"], root=root).parent
    target = root / "data/datasets" / new_id
    mapping = {p: target if p == base else target / "annotations" / p.name for p in roots}
    def mapped(value):
        p = resolve_project_path(value, root=root)
        for old, new in sorted(mapping.items(), key=lambda pair: len(str(pair[0])), reverse=True):
            if p == old or p.is_relative_to(old):
                return new / p.relative_to(old)
        raise AppError("OWNERSHIP_INVALID", f"复制材料包含外部引用：{p}")
    try:
        shutil.copytree(base, target)
        for old, new in mapping.items():
            if old != base:
                shutil.copytree(old, new)
        for file in target.rglob("*.list"):
            lines = []
            for line in file.read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    row = line.split("|", 3)
                    if len(row) != 4:
                        raise AppError("TRANSCRIPT_INVALID", "复制数据集的标注格式无效。")
                    row[0] = str(mapped(row[0]))
                    lines.append("|".join(row))
            file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        for file in target.rglob("emotions.json"):
            atomic_json(file, {str(mapped(k)): v for k, v in read_json(file, {}).items()})
        for file in target.rglob("manifest.json"):
            manifest = read_json(file, {})
            if "inputs_sha256" not in manifest:
                continue
            for value, expected in manifest["inputs_sha256"].items():
                original_input = resolve_project_path(value, root=root)
                if not original_input.is_file() or file_hash(original_input) != expected:
                    raise AppError("DATASET_CHANGED", "源特征输入已变化，不能复制为有效特征，请重新提取。")
            manifest["dataset_id"] = new_id
            manifest["inputs_sha256"] = {mapped(k).relative_to(root).as_posix(): file_hash(mapped(k)) for k in manifest["inputs_sha256"]}
            for output in manifest["outputs"]:
                output["path"] = mapped(output["path"]).relative_to(root).as_posix()
                output["bytes"] = (root / output["path"]).stat().st_size
            atomic_json(file, manifest)
        record = dict(original, dataset_id=new_id,
                      display_name=original["display_name"][:60] + " · 副本 " + new_id[-6:])
        for key in ("source_path", "slice_dir", "list_path", "emotions_path", "feature_manifest"):
            if record.get(key):
                record[key] = mapped(record[key]).relative_to(root).as_posix()
        atomic_json(target / "ownership.json", {"dataset_id": new_id, "copied_from": dataset_id})
        atomic_json(index, records + [record])
        return DatasetRecord.model_validate({**record, **{k: resolve_project_path(record[k], root=root) for k in
               ("source_path", "slice_dir", "list_path", "emotions_path", "feature_manifest") if record.get(k)}}), mapping
    except Exception:
        if target.exists():
            checked_tree(target, root)
            shutil.rmtree(target)
        raise


@serialized
def migrate_ownership(root=PROJECT_ROOT):
    from services import task_service
    task_service.try_acquire_gpu()
    try:
        return _migrate_ownership(root)
    finally:
        task_service.release_gpu()


def _migrate_ownership(root):
    """Non-destructive migration: split shared sources and publish ownership manifests."""
    ensure_ready(root)
    index = root / "data/index/voices.json"
    voices = read_json(index)
    validate_records(voices, VoiceProfile, "voice_id")
    seen = set()
    used_weights = set()
    changed = False
    for voice in voices:
        for key in ("gpt_weight", "sovits_weight"):
            if not voice.get(key):
                continue
            path = resolve_project_path(voice[key], root=root)
            if path in used_weights and path.is_file():
                checked(path, root)
                target = checked(root / "data/voices" / voice["voice_id"] / path.name, root)
                if target == path:
                    target = target.with_name(key + path.suffix)
                if target.exists():
                    from services.history_service import file_hash
                    if file_hash(path) != file_hash(target):
                        raise AppError("OWNERSHIP_INVALID", "独立权重目标已存在不同文件，停止迁移。")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                voice[key] = target.relative_to(root).as_posix()
                changed = True
            used_weights.add(path)
            used_weights.add(resolve_project_path(voice[key], root=root))
        if voice["dataset_id"] in seen:
            old_id = voice["dataset_id"]
            clone, mapping = clone_dataset(old_id, root=root)
            for ref in voice.get("references", []):
                path = resolve_project_path(ref["audio_path"], root=root)
                for old, new in mapping.items():
                    if path.is_relative_to(old):
                        ref["audio_path"] = (new / path.relative_to(old)).relative_to(root).as_posix()
                        break
                else:
                    raise AppError("OWNERSHIP_INVALID", "旧音色参考不属于来源数据集。")
            voice["dataset_id"] = clone.dataset_id
            for plan in (root / "data/training").glob("*/plan.json"):
                data = read_json(plan, {})
                if data.get("voice_id") == voice["voice_id"]:
                    # Preserve executed plans; attach ownership without rewriting evidence.
                    atomic_json(plan.parent / "ownership.json", {"dataset_id": clone.dataset_id, "voice_id": voice["voice_id"]})
            changed = True
        seen.add(voice["dataset_id"])
    if changed:
        atomic_json(index, voices)
    manifests = []
    for voice in voices:
        plan = deletion_plan(voice["voice_id"], index, root)
        target = root / "data/ownership" / (hashlib.sha256(voice["voice_id"].encode()).hexdigest() + ".json")
        atomic_json(target, plan)
        manifests.append(plan)
    return manifests
