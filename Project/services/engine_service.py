from __future__ import annotations

import json
from pathlib import Path

from adapters import GPTSoVITSAdapter
from models.schemas import EngineConfig, EngineStatus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = PROJECT_ROOT / "config" / "engine.local.json"


def probe_engine(config_path: Path = LOCAL_CONFIG) -> EngineStatus:
    if not config_path.is_file():
        return EngineStatus(
            configured=False,
            available=False,
            message="尚未配置模型环境，请复制 engine.example.json 为 engine.local.json。",
        )

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        config = EngineConfig.model_validate(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return EngineStatus(
            configured=False,
            available=False,
            message=f"模型配置无效：{exc}",
        )

    return GPTSoVITSAdapter(config).probe_environment()

