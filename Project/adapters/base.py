from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from models.schemas import EngineConfig, EngineStatus


class SpeechEngineAdapter(ABC):
    """Small boundary between project services and an external engine."""

    def __init__(self, config: EngineConfig) -> None:
        self.config = config

    @abstractmethod
    def probe_environment(self) -> EngineStatus:
        raise NotImplementedError

    @staticmethod
    def require_absolute(path: Path, field_name: str) -> Path:
        resolved = path.expanduser().resolve()
        if not resolved.is_absolute():
            raise ValueError(f"{field_name} 必须是绝对路径")
        return resolved

