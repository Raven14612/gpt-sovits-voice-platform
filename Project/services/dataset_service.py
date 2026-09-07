from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import List, Optional

from models.schemas import DatasetRecord

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_INDEX = PROJECT_ROOT / "data" / "index" / "datasets.json"


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
