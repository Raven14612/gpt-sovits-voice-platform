from __future__ import annotations

import json
import os
import tempfile
import hashlib
import re
import shutil
from pathlib import Path
from threading import RLock
from typing import Dict, List, Optional

from models.schemas import AppError, GenerationRecord
from services.wav_service import inspect_wav
from services.project_paths import PROJECT_ROOT, resolve_project_path
from services.storage_lock import serialized
from models.schemas import utc_now

HISTORY_INDEX = PROJECT_ROOT / "data" / "index" / "history.json"
OUTPUT_ROOT = PROJECT_ROOT / "data" / "outputs"
_index_lock = RLock()


def _read() -> List[Dict]:
    if not HISTORY_INDEX.exists():
        return []
    try:
        records = json.loads(HISTORY_INDEX.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError("history must be a list")
        ids = set()
        for item in records:
            GenerationRecord.model_validate(item)
            if item["result_id"] in ids:
                raise ValueError("duplicate result_id")
            ids.add(item["result_id"])
        return records
    except (OSError, ValueError) as exc:
        raise AppError("HISTORY_INDEX_INVALID", "历史索引损坏，已保留原文件并停止写入。") from exc


def output_path(value) -> Path:
    path = resolve_project_path(value, root=PROJECT_ROOT)
    if not path.is_relative_to(OUTPUT_ROOT.resolve()) or path.suffix.lower() != ".wav":
        raise AppError("OUTPUT_INVALID", "结果必须是项目 data/outputs 内的 WAV。")
    return path


def list_history() -> List[Dict]:
    with _index_lock:
        valid = []
        for record in _read():
            if record.get("status") != "succeeded" or not record.get("output_path"):
                continue
            try:
                inspect_wav(output_path(record["output_path"]))
                valid.append(record)
            except AppError:
                pass
        return valid


def _write(records, index_path=None):
    index_path = index_path or HISTORY_INDEX
    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="history-", suffix=".json", dir=index_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, index_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@serialized
def add_history(record: GenerationRecord) -> GenerationRecord:
    with _index_lock:
        records = _read()
        if record.status != "succeeded" or not record.output_path:
            raise AppError("OUTPUT_INVALID", "只有有效 WAV 输出才能写入成功历史。")
        path = output_path(record.output_path)
        inspect_wav(path)
        for existing in records:
            old_path = existing.get("output_path")
            if not old_path:
                continue
            resolved = output_path(old_path)
            if existing["result_id"] == record.result_id and resolved != path:
                raise AppError("RESULT_CONFLICT", "同一结果 ID 不能替换为另一个文件。")
            if existing["result_id"] != record.result_id and resolved == path:
                raise AppError("RESULT_CONFLICT", "一个 WAV 不能被多个结果共同拥有。")
        data = record.model_dump(mode="json")
        if not data.get("source_snapshot"):
            data["source_snapshot"] = source_snapshot(record.voice_id, record.emotion)
        data["display_name"] = data.get("display_name") or record.text[:80]
        data["output_path"] = path.relative_to(PROJECT_ROOT.resolve()).as_posix()
        _write([item for item in records if item["result_id"] != record.result_id] + [data])
    return record


upsert_history = add_history


def get_history(result_id: str) -> Optional[Dict]:
    with _index_lock:
        return next((item for item in _read() if item["result_id"] == result_id), None)


def get_result_output(result_id: str):
    with _index_lock:
        record = get_history(result_id)
        if record is None:
            return None
        if record.get("status") != "succeeded" or not record.get("output_path"):
            raise AppError("OUTPUT_INVALID", "该记录没有成功生成的音频。")
        path = output_path(record["output_path"])
        inspect_wav(path)
        return str(path)


@serialized
def delete_history(result_id: str) -> bool:
    with _index_lock:
        records = _read()
        record = next((item for item in records if item["result_id"] == result_id), None)
        if record is None:
            return False
        path = output_path(record["output_path"]) if record.get("output_path") else None
        tombstone = path.with_suffix(".wav.deleting") if path else None
        moved = False
        try:
            if path and path.exists():
                if tombstone.exists():
                    raise AppError("HISTORY_DELETE_FAILED", "存在未恢复的删除事务，请重启应用。")
                os.replace(path, tombstone)
                moved = True
            try:
                _write([item for item in records if item["result_id"] != result_id])
            except Exception:
                if moved:
                    os.replace(tombstone, path)
                raise
            if moved:
                # A crash or unlink failure here is completed by startup recovery.
                tombstone.unlink()
            _remove_downloads(result_id)
        except OSError as exc:
            raise AppError("HISTORY_DELETE_FAILED", "删除未完全完成，请检查文件占用并刷新或重启恢复。") from exc
        return True


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_snapshot(voice_id, emotion, *, profile=None, reference_path=None, prompt_text=None,
                    historical=False):
    from services import voice_service, dataset_service
    profile = profile or voice_service.get_voice(voice_id)
    dataset = dataset_service.get_dataset(profile.dataset_id) if profile else None
    snapshot = {"voice_id": voice_id, "voice_name": profile.display_name if profile else voice_id,
                "dataset_id": profile.dataset_id if profile else None,
                "dataset_name": dataset.display_name if dataset else "来源未记录",
                "provenance": "legacy_backfill" if historical else "generation"}
    if profile:
        if profile.origin_type == "workshop":
            snapshot.update(dataset_name="创意工坊", origin_type="workshop", origin_workshop_id=profile.origin_workshop_id)
        for key in ("gpt_weight", "sovits_weight"):
            path = getattr(profile, key)
            snapshot[key] = {"name": path.name if path else None}
            # A legacy record cannot prove which historical file bytes were used.
            if not historical and path and path.is_file():
                snapshot[key]["sha256"] = file_hash(path)
        ref = next((r for r in profile.references if r.emotion == emotion), None)
        if ref:
            path = Path(reference_path or ref.audio_path)
            snapshot["reference"] = {"name": path.name, "text": prompt_text if prompt_text is not None else ref.prompt_text,
                                     "language": ref.language}
            if not historical and path.is_file():
                snapshot["reference"]["sha256"] = file_hash(path)
    return snapshot


@serialized
def backfill_snapshots():
    """Freeze available legacy names once, before voices/datasets can be removed."""
    with _index_lock:
        records = _read()
        changed = 0
        for record in records:
            if not record.get("source_snapshot"):
                record["source_snapshot"] = source_snapshot(record["voice_id"], record.get("emotion", "neutral"), historical=True)
                record.setdefault("display_name", record["text"][:80])
                changed += 1
        if changed:
            _write(records)
        return changed


@serialized
def edit_result(result_id, display_name, notes=""):
    name, notes = str(display_name or "").strip(), str(notes or "").strip()
    if not name or len(name) > 80 or len(notes) > 2000:
        raise AppError("INVALID_RESULT_NAME", "成品名称须为 1–80 字，备注最多 2000 字。")
    with _index_lock:
        records = _read()
        record = next((r for r in records if r["result_id"] == result_id), None)
        if record is None or not get_result_output(result_id):
            raise AppError("OUTPUT_INVALID", "请选择有效成品。")
        record.update(display_name=name, notes=notes, updated_at=utc_now().isoformat())
        _write(records)
        return record


def download_result(result_id):
    with _index_lock:
        record = get_history(result_id)
        source = get_result_output(result_id)
        if not record or not source:
            raise AppError("OUTPUT_INVALID", "请选择有效成品。")
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", record.get("display_name") or record["text"][:80]).strip(" .") or "成品语音"
        # Prefix avoids reserved Windows filenames while preserving the Chinese title.
        target = _download_directory(result_id) / ("语音_" + name + ".wav")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return str(target)


def _download_directory(result_id):
    return PROJECT_ROOT / "data/tmp/result-downloads" / hashlib.sha256(result_id.encode()).hexdigest()[:24]


def _remove_downloads(result_id):
    from services.asset_service import checked_tree
    directory = _download_directory(result_id)
    if directory.exists():
        checked_tree(directory, PROJECT_ROOT, areas=("tmp/result-downloads",))
        shutil.rmtree(directory)


def reuse_history(result_id: str) -> Dict:
    with _index_lock:
        record = get_history(result_id)
        if not record or not get_result_output(result_id):
            raise AppError("OUTPUT_INVALID", "只能复用有效的成功历史。")
        return record


def recover_history() -> dict:
    """Only run before accepting requests; preserve corrupt indices and orphan WAVs."""
    with _index_lock:
        records = _read()
        report = {"restored": [], "removed_temporary": [], "invalid_results": [], "orphan_outputs": []}
        owned = {output_path(item["output_path"]) for item in records if item.get("output_path")}
        if OUTPUT_ROOT.exists():
            for item in OUTPUT_ROOT.rglob("*.wav.deleting"):
                if not item.resolve().is_relative_to(OUTPUT_ROOT.resolve()):
                    continue
                original = output_path(item.with_suffix(""))
                if original in owned:
                    os.replace(item, original)
                    report["restored"].append(original.name)
                else:
                    item.unlink()
                    report["removed_temporary"].append(item.name)
            for item in OUTPUT_ROOT.rglob("tts-*.wav.part"):
                if item.resolve().is_relative_to(OUTPUT_ROOT.resolve()):
                    item.unlink()
                    report["removed_temporary"].append(item.name)
        for record in records:
            if record.get("status") == "succeeded":
                try:
                    inspect_wav(output_path(record["output_path"]))
                except (AppError, KeyError, TypeError):
                    report["invalid_results"].append(record["result_id"])
                    record["status"] = "output_invalid"
        if report["invalid_results"]:
            _write(records)
        download_root = PROJECT_ROOT / "data/tmp/result-downloads"
        owned_downloads = {_download_directory(r["result_id"]) for r in records}
        for directory in download_root.glob("*"):
            if directory not in owned_downloads and re.fullmatch(r"[0-9a-f]{24}", directory.name):
                from services.asset_service import checked_tree
                checked_tree(directory, PROJECT_ROOT, areas=("tmp/result-downloads",))
                if directory.is_dir():
                    shutil.rmtree(directory)
        if OUTPUT_ROOT.exists():
            report["orphan_outputs"] = [p.relative_to(OUTPUT_ROOT).as_posix()
                                        for p in OUTPUT_ROOT.rglob("*.wav")
                                        if p.resolve().is_relative_to(OUTPUT_ROOT.resolve()) and p.resolve() not in owned]
        return report
