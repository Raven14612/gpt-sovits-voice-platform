from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

LICENSES = ("CC BY 4.0", "CC BY-NC 4.0", "仅限获得作者许可后使用")
MAX_PACKAGE_BYTES = 1024 ** 3


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Engine(StrictModel):
    family: Literal["GPT-SoVITS"]
    model_version: Literal["v2Pro"]


class Reference(StrictModel):
    emotion: Literal["neutral", "happy", "sad"]
    path: str
    prompt_text: str = Field(min_length=1, max_length=2000)
    language: Literal["zh"]


class Voice(StrictModel):
    display_name: str = Field(min_length=1, max_length=80)
    author: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=2000)
    emotions: list[Literal["neutral", "happy", "sad"]] = Field(min_length=1, max_length=3)
    references: list[Reference] = Field(min_length=1, max_length=3)


class License(StrictModel):
    name: Literal["CC BY 4.0", "CC BY-NC 4.0", "仅限获得作者许可后使用"]
    rights_confirmed: Literal[True]


class PackageFile(StrictModel):
    role: Literal["gpt_weight", "sovits_weight", "reference"]
    path: str
    bytes: int = Field(gt=0, le=MAX_PACKAGE_BYTES, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest(StrictModel):
    schema_version: Literal[1]
    package_id: UUID
    created_at: datetime
    client_min_version: Literal["2.0"]
    engine: Engine
    voice: Voice
    license: License
    files: list[PackageFile] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def coherent(self):
        if self.created_at.tzinfo is None:
            raise ValueError("created_at requires timezone")
        refs = self.voice.references
        emotions = self.voice.emotions
        if len(set(emotions)) != len(emotions) or sorted(emotions) != sorted(ref.emotion for ref in refs):
            raise ValueError("reference coverage")
        expected = {"weights/gpt.ckpt": "gpt_weight", "weights/sovits.pth": "sovits_weight"}
        for ref in refs:
            if ref.path != f"references/{ref.emotion}.wav" or not ref.prompt_text.strip():
                raise ValueError("reference path")
            expected[ref.path] = "reference"
        if len(self.files) != len(expected) or {f.path: f.role for f in self.files} != expected:
            raise ValueError("file whitelist")
        if not all(s.strip() for s in (self.voice.display_name, self.voice.author, self.voice.description)):
            raise ValueError("empty display metadata")
        return self
