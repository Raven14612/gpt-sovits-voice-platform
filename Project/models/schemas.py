from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        detail: Optional[Dict[str, Any]] = None,
        stage: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}
        self.stage = stage


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EngineConfig(BaseModel):
    profile: str = "local-gpt-sovits"
    engine_root: Path
    python_path: Path
    max_gpu_jobs: Literal[1] = 1
    parallel_infer: Literal[False] = False


class EngineStatus(BaseModel):
    configured: bool
    available: bool
    python_version: Optional[str] = None
    torch_version: Optional[str] = None
    cuda_version: Optional[str] = None
    gpu_name: Optional[str] = None
    message: str


class TaskRecord(BaseModel):
    task_id: str
    kind: str
    status: TaskStatus = TaskStatus.PENDING
    stage: str = "waiting"
    message: str = "等待执行"
    log_path: Optional[Path] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class EmotionReference(BaseModel):
    emotion: Literal["neutral", "happy", "sad"]
    audio_path: Path
    prompt_text: str = Field(min_length=1)
    language: Literal["zh"] = "zh"


class DatasetRecord(BaseModel):
    dataset_id: str
    display_name: str = Field(min_length=1, max_length=80)
    source_path: Path
    slice_dir: Optional[Path] = None
    list_path: Optional[Path] = None
    emotions_path: Optional[Path] = None
    status: str = "created"
    created_at: datetime = Field(default_factory=utc_now)


class VoiceProfile(BaseModel):
    voice_id: str
    display_name: str = Field(min_length=1, max_length=80)
    feature_name: str = Field(min_length=1, max_length=80)
    dataset_id: str
    gpt_weight: Optional[Path] = None
    sovits_weight: Optional[Path] = None
    references: List[EmotionReference] = Field(default_factory=list)
    engine_profile: str
    status: str = "draft"
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def unique_emotions(self) -> "VoiceProfile":
        emotions = [item.emotion for item in self.references]
        if len(emotions) != len(set(emotions)):
            raise ValueError("同一种情绪只能保存一条主参考音频")
        return self


class GenerationRecord(BaseModel):
    result_id: str
    voice_id: str
    text: str = Field(min_length=1, max_length=500)
    emotion: Literal["neutral", "happy", "sad"] = "neutral"
    speed_factor: float = Field(default=1.0, ge=0.5, le=2.0)
    fragment_interval: float = Field(default=0.3, ge=0.0, le=2.0)
    output_path: Optional[Path] = None
    status: str = "pending"
    created_at: datetime = Field(default_factory=utc_now)
