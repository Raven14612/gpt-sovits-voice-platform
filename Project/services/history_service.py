from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

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
