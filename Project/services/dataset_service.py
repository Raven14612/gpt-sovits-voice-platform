from __future__ import annotations

import json
import os
import shutil
import tempfile
import wave
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from models.schemas import AppError, DatasetRecord

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_INDEX = PROJECT_ROOT / "data" / "index" / "datasets.json"
DATASET_ROOT = PROJECT_ROOT / "data" / "datasets"


def list_datasets(index_path: Path = DATASET_INDEX) -> List[DatasetRecord]:
    if not index_path.is_file():
        return []
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
        return [DatasetRecord.model_validate(item) for item in raw] if isinstance(raw, list) else []
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def get_dataset(dataset_id: str, index_path: Path = DATASET_INDEX) -> Optional[DatasetRecord]:
    return next((item for item in list_datasets(index_path) if item.dataset_id == dataset_id), None)


def upsert_dataset(record: DatasetRecord, index_path: Path = DATASET_INDEX) -> DatasetRecord:
    records = [item for item in list_datasets(index_path) if item.dataset_id != record.dataset_id]
    records.append(record)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="datasets-", suffix=".json", dir=index_path.parent)
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
    return record


def delete_dataset(dataset_id: str, index_path: Path = DATASET_INDEX) -> bool:
    records = list_datasets(index_path)
    kept = [item for item in records if item.dataset_id != dataset_id]
    if len(kept) == len(records):
        return False
    index_path.parent.mkdir(parents=True, exist_ok=True)
    temp = index_path.with_suffix(".tmp")
    temp.write_text(json.dumps([item.model_dump(mode="json") for item in kept], ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, index_path)
    return True


def import_audio(source: str, display_name: str, *, index_path: Path = DATASET_INDEX,
                 data_root: Path = DATASET_ROOT) -> DatasetRecord:
    if not source:
        raise AppError("INVALID_AUDIO", "请先上传音频。")
    path = Path(source).resolve()
    name = display_name.strip() or path.stem
    if len(name) > 80:
        raise AppError("INVALID_DATASET", "数据集名称最多 80 个字符。")
    try:
        with wave.open(str(path), "rb") as info:
            if info.getnframes() <= 0 or info.getframerate() <= 0 or not info.readframes(1):
                raise ValueError("empty audio")
    except (OSError, EOFError, wave.Error, ValueError) as exc:
        raise AppError("INVALID_AUDIO", "音频无法读取或内容为空，请上传 PCM WAV 音频。") from exc
    dataset_id = uuid4().hex
    directory = data_root / dataset_id
    directory.mkdir(parents=True, exist_ok=False)
    try:
        target = directory / ("source" + path.suffix.lower())
        shutil.copy2(path, target)
        record = DatasetRecord(dataset_id=dataset_id, display_name=name, source_path=target)
        return upsert_dataset(record, index_path)
    except Exception:
        shutil.rmtree(directory)
        raise


def _dataset_or_error(dataset_id: str, index_path: Path) -> DatasetRecord:
    record = get_dataset(dataset_id, index_path)
    if record is None:
        raise AppError("DATASET_MISSING", "请先选择已保存的数据集。")
    return record


def _read_transcript(path: Path) -> list:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise AppError("TRANSCRIPT_INVALID", "识别文本无法读取，需要 UTF-8 编码的 .list 文件。") from exc
    records = []
    for line in lines:
        if not line.strip():
            continue
        fields = line.split("|", 3)
        if len(fields) != 4 or any(not part.strip() for part in fields) or fields[2].lower() != "zh":
            raise AppError("TRANSCRIPT_INVALID", "识别文本格式应为：音频路径|说话人|zh|文本。")
        records.append(fields)
    if not records or len({row[0] for row in records}) != len(records):
        raise AppError("TRANSCRIPT_INVALID", "识别文本为空或包含重复切片。")
    return records


def load_corrections(dataset_id: str, index_path: Path = DATASET_INDEX) -> list:
    record = _dataset_or_error(dataset_id, index_path)
    if record.list_path is None:
        return []
    lines = _read_transcript(record.list_path)
    emotions = {}
    if record.emotions_path:
        try:
            emotions = json.loads(record.emotions_path.read_text(encoding="utf-8"))
            if not isinstance(emotions, dict) or any(value not in {"neutral", "happy", "sad"} for value in emotions.values()):
                raise ValueError("invalid emotions")
        except (OSError, ValueError) as exc:
            raise AppError("TRANSCRIPT_INVALID", "情绪标签文件无法读取。") from exc
    return [[row[0], row[3], emotions.get(row[0], "neutral")] for row in lines]


def import_transcript(dataset_id: str, source: str, *, index_path: Path = DATASET_INDEX,
                      data_root: Path = DATASET_ROOT) -> DatasetRecord:
    record = _dataset_or_error(dataset_id, index_path)
    if not source:
        raise AppError("TRANSCRIPT_INVALID", "请先上传识别文本。")
    lines = _read_transcript(Path(source))
    return _save_transcript(record, lines, {}, "transcribed", index_path, data_root)


def save_corrections(dataset_id: str, rows: list, *, index_path: Path = DATASET_INDEX,
                     data_root: Path = DATASET_ROOT) -> DatasetRecord:
    record = _dataset_or_error(dataset_id, index_path)
    if record.list_path is None:
        raise AppError("TRANSCRIPT_MISSING", "尚无识别文本可供校对。")
    original = _read_transcript(record.list_path)
    if len(rows) != len(original):
        raise AppError("TRANSCRIPT_INVALID", "切片数量已变化，请重新加载数据集。")
    lines, emotions = [], {}
    for source, row in zip(original, rows):
        if len(row) != 3 or row[0] != source[0]:
            raise AppError("TRANSCRIPT_INVALID", "切片路径和顺序不能修改。")
        text, emotion = str(row[1]).strip(), row[2]
        if not text or any(char in text for char in "\r\n|") or emotion not in {"neutral", "happy", "sad"}:
            raise AppError("TRANSCRIPT_INVALID", "文本不能为空或含换行/分隔符；情绪仅支持 neutral、happy、sad。")
        lines.append([*source[:3], text])
        emotions[source[0]] = emotion
    return _save_transcript(record, lines, emotions, "reviewed", index_path, data_root)


def _save_transcript(record, lines, emotions, status, index_path, data_root):
    # New revision files become visible together when the index is atomically replaced.
    directory = data_root.resolve() / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    try:
        transcript = directory / "corrected.list"
        labels = directory / "emotions.json"
        transcript.write_text("\n".join("|".join(row) for row in lines) + "\n", encoding="utf-8")
        labels.write_text(json.dumps(emotions, ensure_ascii=False, indent=2), encoding="utf-8")
        return upsert_dataset(record.model_copy(update={
            "list_path": transcript, "emotions_path": labels, "status": status,
        }), index_path)
    except Exception:
        shutil.rmtree(directory)
        raise
