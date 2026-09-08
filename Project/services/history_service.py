from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List
from models.schemas import AppError

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
