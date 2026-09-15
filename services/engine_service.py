from __future__ import annotations

import json
from pathlib import Path

from adapters import GPTSoVITSAdapter
from models.schemas import EngineConfig, EngineStatus
from services.project_paths import PROJECT_ROOT, resolve_project_path

LOCAL_CONFIG = PROJECT_ROOT / "config" / "engine.local.json"


def load_engine_config(config_path: Path = LOCAL_CONFIG) -> EngineConfig:
    """Load config and resolve relative paths from the Project root."""
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    for key in ("engine_root", "python_path"):
        raw[key] = str(resolve_project_path(raw[key], root=PROJECT_ROOT))
    return EngineConfig.model_validate(raw)


def probe_engine(config_path: Path = LOCAL_CONFIG) -> EngineStatus:
    if not config_path.is_file():
        return EngineStatus(
            configured=False,
            available=False,
            message="尚未配置模型环境，请复制 engine.example.json 为 engine.local.json。",
        )

    try:
        config = load_engine_config(config_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return EngineStatus(
            configured=False,
            available=False,
            message=f"模型配置无效：{exc}",
        )

    return GPTSoVITSAdapter(config).probe_environment()
