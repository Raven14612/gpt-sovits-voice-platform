from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from typing import Literal  # type: ignore
except ImportError:  # Python < 3.8
    from typing_extensions import Literal  # type: ignore

from pydantic import BaseModel, Field

try:
    from pydantic import model_validator  # type: ignore
except ImportError:  # pydantic v1
    from pydantic import root_validator

    def model_validator(*, mode: str = "after"):
        if mode != "after":
            raise NotImplementedError("Only after validators are supported on pydantic v1.")

        def decorator(fn):
            @root_validator
            def _wrapper(cls, values):
                fn(cls.construct(**values))
                return values

            return _wrapper

        return decorator


if hasattr(BaseModel, "model_validate"):
    class CompatBaseModel(BaseModel):
        pass
else:
    class CompatBaseModel(BaseModel):
        @classmethod
        def model_validate(cls, obj):
            return cls.parse_obj(obj)

        def model_dump(self, *args, **kwargs):
            mode = kwargs.pop("mode", "python")
            if mode == "json":
                return json.loads(self.json(*args, **kwargs))
            return self.dict(*args, **kwargs)

        def model_copy(self, *, update=None, **kwargs):
            return self.copy(update=update or {}, **kwargs)


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


class EngineConfig(CompatBaseModel):
    profile: str = "local-gpt-sovits"
    engine_root: Path
    python_path: Path
    max_gpu_jobs: Literal[1] = 1
    parallel_infer: Literal[False] = False


class EngineStatus(CompatBaseModel):
    configured: bool
    available: bool
    python_version: Optional[str] = None
    torch_version: Optional[str] = None
    cuda_version: Optional[str] = None
    gpu_name: Optional[str] = None
    message: str


class TaskRecord(CompatBaseModel):
    task_id: str
    kind: str
    status: TaskStatus = TaskStatus.PENDING
    stage: str = "waiting"
    message: str = "等待执行"
    log_path: Optional[Path] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class EmotionReference(CompatBaseModel):
    emotion: Literal["neutral", "happy", "sad"]
    audio_path: Path
    prompt_text: str = Field(min_length=1)
    language: Literal["zh"] = "zh"


class DatasetRecord(CompatBaseModel):
    dataset_id: str
    display_name: str = Field(min_length=1, max_length=80)
    source_path: Path
    slice_dir: Optional[Path] = None
    list_path: Optional[Path] = None
    emotions_path: Optional[Path] = None
    status: str = "created"
    created_at: datetime = Field(default_factory=utc_now)


class VoiceProfile(CompatBaseModel):
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


class GenerationRecord(CompatBaseModel):
    result_id: str
    voice_id: str
    text: str = Field(min_length=1, max_length=500)
    emotion: Literal["neutral", "happy", "sad"] = "neutral"
    speed_factor: float = Field(default=1.0, ge=0.5, le=2.0)
    fragment_interval: float = Field(default=0.3, ge=0.0, le=2.0)
    output_path: Optional[Path] = None
    status: str = "pending"
    created_at: datetime = Field(default_factory=utc_now)
