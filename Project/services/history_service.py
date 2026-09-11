from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List
from models.schemas import AppError, GenerationRecord

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HISTORY_INDEX = PROJECT_ROOT / "data" / "index" / "history.json"


def list_history() -> List[Dict]:
    if not HISTORY_INDEX.is_file():
        return []
    try:
        data = json.loads(HISTORY_INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def get_result_output(result_id: str):
    record = next((item for item in list_history() if item.get("result_id") == result_id), None)
    if record is None:
        return None
    if record.get("status") != "succeeded" or not record.get("output_path"):
        raise AppError("OUTPUT_INVALID", "该记录没有成功生成的音频。")
    path = Path(record["output_path"])
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if not path.is_relative_to((PROJECT_ROOT / "data" / "outputs").resolve()) or not path.is_file():
        raise AppError("OUTPUT_INVALID", "结果音频不存在或位于项目输出目录之外。")
    return str(path)


def add_history(record: GenerationRecord) -> GenerationRecord:
    records = [item for item in list_history() if item.get("result_id") != record.result_id]
    data = record.model_dump(mode="json")
    if data.get("output_path"):
        output = Path(data["output_path"]).resolve()
        try:
            data["output_path"] = output.relative_to(PROJECT_ROOT.resolve()).as_posix()
        except ValueError as exc:
            raise AppError("OUTPUT_INVALID", "结果音频必须位于项目目录内。") from exc
    records.append(data)
    HISTORY_INDEX.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="history-", suffix=".json", dir=HISTORY_INDEX.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, HISTORY_INDEX)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return record
