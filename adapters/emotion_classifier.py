"""Offline, manifest-pinned ONNX text classification. Never imports torch."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit

from models.schemas import AppError
from services.project_paths import PROJECT_ROOT, resolve_project_path

MODEL_DIR = "models/emotion/emotion-zh-v1"
MODEL_ID = "emotion-zh-v1"
_lock = RLock()
_cache = {}


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def map_label(label):
    mapped = {"neutral": "neutral", "happy": "happy", "joy": "happy",
              "sad": "sad", "sadness": "sad"}.get(label.lower())
    return mapped or "neutral", mapped is None


def load_config(*, root=PROJECT_ROOT):
    defaults = dict(model_id=MODEL_ID, relative_dir=MODEL_DIR, download_page="",
                    manifest_sha256="", max_length=256, high_confidence_threshold=0.8)
    try:
        path = Path(root) / "config/emotion-model.local.json"
        if path.is_file():
            defaults.update(json.loads(path.read_text(encoding="utf-8")))
        if (defaults["model_id"] != MODEL_ID or defaults["relative_dir"] != MODEL_DIR
                or defaults["max_length"] != 256
                or not 0 <= float(defaults["high_confidence_threshold"]) <= 1):
            raise ValueError("unsupported configuration")
        url = defaults["download_page"]
        if url and (urlsplit(url).scheme != "https" or not urlsplit(url).hostname
                    or urlsplit(url).username or any(c in url for c in "\r\n<>\"")):
            raise ValueError("invalid download page")
        return defaults
    except (OSError, ValueError, TypeError) as exc:
        raise AppError("EMOTION_MODEL_INVALID", "情绪模型配置无效，请联系发布者。") from exc


def installation_message(config):
    download = config["download_page"] or "请联系发布者配置模型下载地址"
    return f"尚未安装情绪判断模型。下载页面：{download}；解压目标：{MODEL_DIR}/"


class EmotionClassifier:
    def __init__(self, *, root=PROJECT_ROOT):
        self.root = Path(root).resolve()
        self.config = load_config(root=self.root)
        self.directory = resolve_project_path(MODEL_DIR, root=self.root)
        self.manifest = None

    def _validate(self):
        if not self.directory.is_dir():
            raise AppError("EMOTION_MODEL_MISSING", installation_message(self.config))
        try:
            # Reject redirected resources; only the one documented location is allowed.
            if self.directory != self.root / MODEL_DIR:
                raise ValueError("redirected model directory")
            path = self.directory / "model-manifest.json"
            if path.resolve() != path or file_hash(path) != self.config["manifest_sha256"]:
                raise ValueError("manifest hash")
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if (manifest["schema_version"] != 1 or manifest["model_id"] != MODEL_ID
                    or manifest["max_length"] != self.config["max_length"]
                    or manifest["format"] not in {"int8", "fp32", "fp16"}
                    or not manifest["model_version"]):
                raise ValueError("manifest version")
            labels = manifest["labels"]
            if (not isinstance(labels, list) or not labels or len(labels) != len(set(labels))
                    or any(not isinstance(label, str) or not label for label in labels)):
                raise ValueError("labels")
            files = manifest["files"]
            if set(files) != {"model.onnx", "tokenizer.json", "LICENSE.txt", "README.txt"}:
                raise ValueError("resource whitelist")
            for name, info in files.items():
                resource = self.directory / name
                if (resource.resolve() != resource or resource.stat().st_size != info["bytes"]
                        or not re.fullmatch(r"[0-9a-f]{64}", info["sha256"])
                        or file_hash(resource) != info["sha256"]):
                    raise ValueError("resource hash")
            self.manifest = manifest
            return manifest
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise AppError("EMOTION_MODEL_INVALID", "情绪模型清单、版本或文件校验失败，请重新解压发布模型包。") from exc

    def load(self):
        manifest = self._validate()
        key = (str(self.directory), self.config["manifest_sha256"])
        with _lock:
            if key not in _cache:
                try:
                    import onnxruntime as ort
                    from tokenizers import Tokenizer
                    tokenizer = Tokenizer.from_file(str(self.directory / "tokenizer.json"))
                    tokenizer.enable_truncation(max_length=manifest["max_length"])
                    tokenizer.enable_padding(length=manifest["max_length"], pad_id=manifest["pad_token_id"],
                                             pad_token=manifest["pad_token"])
                    options = ort.SessionOptions()
                    options.intra_op_num_threads = 2
                    options.inter_op_num_threads = 1
                    session = ort.InferenceSession(str(self.directory / "model.onnx"), sess_options=options,
                                                   providers=["CPUExecutionProvider"])
                    if session.get_providers() != ["CPUExecutionProvider"]:
                        raise ValueError("CPU provider required")
                    inputs = session.get_inputs()
                    if (not inputs or any(i.name not in {"input_ids", "attention_mask", "token_type_ids"}
                                          or i.type != "tensor(int64)" for i in inputs)):
                        raise ValueError("ONNX inputs")
                    outputs = session.get_outputs()
                    if len(outputs) != 1 or len(outputs[0].shape) != 2 or outputs[0].shape[1] != len(manifest["labels"]):
                        raise ValueError("ONNX output dimension")
                    _cache.clear()
                    _cache[key] = tokenizer, session
                except Exception as exc:
                    raise AppError("EMOTION_MODEL_INVALID", "情绪模型无法在 CPU 运行时加载，请检查运行包版本。") from exc
            self.tokenizer, self.session = _cache[key]
        return self

    def predict(self, texts, *, batch_size=16):
        if not hasattr(self, "session"):
            self.load()
        try:
            import numpy as np
            result = []
            for start in range(0, len(texts), batch_size):
                encodings = self.tokenizer.encode_batch(texts[start:start + batch_size])
                arrays = {"input_ids": [e.ids for e in encodings], "attention_mask": [e.attention_mask for e in encodings],
                          "token_type_ids": [e.type_ids for e in encodings]}
                feed = {i.name: np.asarray(arrays[i.name], dtype=np.int64) for i in self.session.get_inputs()}
                logits = np.asarray(self.session.run(None, feed)[0], dtype=np.float64)
                if logits.shape != (len(encodings), len(self.manifest["labels"])) or not np.isfinite(logits).all():
                    raise ValueError("invalid logits")
                probabilities = np.exp(logits - logits.max(axis=1, keepdims=True))
                probabilities /= probabilities.sum(axis=1, keepdims=True)
                result.extend(dict(zip(self.manifest["labels"], map(float, row))) for row in probabilities)
            return result
        except Exception as exc:
            raise AppError("EMOTION_MODEL_INVALID", "情绪模型推理失败，原标注已保留。") from exc
