"""Sidecar suggestions; only dataset_service.save_corrections publishes training labels."""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

from adapters.emotion_classifier import EmotionClassifier, file_hash, load_config, map_label
from models.schemas import AppError, EmotionSuggestionFile, EmotionSuggestionItem
from services import dataset_service
from services.asset_service import checked
from services.path_migration import atomic_write, encoded
from services.project_paths import PROJECT_ROOT, resolve_project_path
from services.storage_lock import metadata_lock


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def probe_emotion_model():
    try:
        classifier = EmotionClassifier().load()
        return dict(available=True, code="", message="模型可用（CPU；仅提供文本语义建议）",
                    **classifier.config)
    except AppError as exc:
        return dict(available=False, code=exc.code, message=exc.message)


def _snapshot(dataset_id):
    record = dataset_service._dataset_or_error(dataset_id, dataset_service.DATASET_INDEX)
    if not record.list_path or not record.slice_dir:
        raise AppError("TRANSCRIPT_MISSING", "请先完成切分并识别。")
    for path in (record.source_path, record.list_path, record.slice_dir):
        checked(path, PROJECT_ROOT, areas=("datasets",))
    digest = file_hash(record.list_path)
    rows = dataset_service._read_transcript(record.list_path)
    wavs = {p.resolve() for p in record.slice_dir.glob("*.wav")}
    paths = [resolve_project_path(row[0], root=PROJECT_ROOT) for row in rows]
    if not wavs or len(paths) != len(wavs) or set(paths) != wavs:
        raise AppError("TRANSCRIPT_INVALID", "标注与当前切片不一一对应，请重新识别。")
    for path in paths:
        checked(path, PROJECT_ROOT, areas=("datasets",))
        if not path.is_relative_to(record.slice_dir.resolve()):
            raise AppError("TRANSCRIPT_INVALID", "切片路径越界。")
    if file_hash(record.list_path) != digest:
        raise AppError("DATASET_CHANGED", "标注已变化，请重新加载。")
    return record, rows, digest


def _target(record):
    return checked(record.list_path.parent / "emotion-suggestions-v1.json", PROJECT_ROOT, areas=("datasets",))


def load_suggestions(dataset_id):
    record, rows, digest = _snapshot(dataset_id)
    if not record.emotion_suggestions_path:
        return None
    if record.emotion_suggestions_path.resolve() != _target(record):
        return None
    try:
        value = EmotionSuggestionFile.model_validate(json.loads(record.emotion_suggestions_path.read_text(encoding="utf-8")))
        if (value.dataset_id != dataset_id or value.annotation_sha256 != digest
                or resolve_project_path(value.annotation_path, root=PROJECT_ROOT) != record.list_path.resolve()):
            return None
        actual = {resolve_project_path(row[0], root=PROJECT_ROOT): text_hash(row[3]) for row in rows}
        paths = [resolve_project_path(item.audio_path, root=PROJECT_ROOT) for item in value.items]
        if len(paths) != len(set(paths)) or any(actual.get(path) != item.text_sha256 for path, item in zip(paths, value.items)):
            return None
        return value
    except (OSError, ValueError):
        return None


def _publish(record, digest, value, *, previous_hash):
    """Stage before compare-and-swap; failed index publication restores old sidecar."""
    target = _target(record)
    fd, name = tempfile.mkstemp(prefix=".emotion-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded(value.model_dump(mode="json")))
            handle.flush()
            os.fsync(handle.fileno())
        with metadata_lock():
            current, _, latest_hash = _snapshot(record.dataset_id)
            if (current != record or latest_hash != digest
                    or (file_hash(target) if target.exists() else None) != previous_hash):
                raise AppError("DATASET_CHANGED", "情绪判断期间数据集或建议已更新，请重新加载后重试。")
            previous = target.read_bytes() if target.exists() else None
            os.replace(name, target)
            try:
                dataset_service.upsert_dataset(record.model_copy(update={"emotion_suggestions_path": target}),
                                               dataset_service.DATASET_INDEX)
            except Exception:
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    atomic_write(target, previous)
                raise
    finally:
        Path(name).unlink(missing_ok=True)


def suggest_emotions(dataset_id, *, only_unaccepted=True, protected_paths=()):
    with metadata_lock():
        record, rows, digest = _snapshot(dataset_id)
        previous = load_suggestions(dataset_id)
        target = _target(record)
        previous_hash = file_hash(target) if target.exists() else None
    classifier = EmotionClassifier().load()
    existing = {resolve_project_path(i.audio_path, root=PROJECT_ROOT): i for i in previous.items} if previous else {}
    protected = {resolve_project_path(p, root=PROJECT_ROOT) for p in protected_paths}
    indices = [i for i, row in enumerate(rows) if not (only_unaccepted and (
        record.status == "reviewed" or resolve_project_path(row[0], root=PROJECT_ROOT) in protected
        or (existing.get(resolve_project_path(row[0], root=PROJECT_ROOT)) and
            existing[resolve_project_path(row[0], root=PROJECT_ROOT)].accepted)))]
    texts = [f"[上文] {rows[i-1][3] if i else ''} [当前] {rows[i][3]} [下文] {rows[i+1][3] if i+1 < len(rows) else ''}"
             for i in indices]
    predictions = classifier.predict(texts)
    if len(predictions) != len(indices):
        raise AppError("EMOTION_MODEL_INVALID", "情绪模型返回条目数不正确。")
    for i, probabilities in zip(indices, predictions):
        if (not probabilities or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values())
                or abs(sum(probabilities.values()) - 1) > 0.001):
            raise AppError("EMOTION_MODEL_INVALID", "情绪模型概率输出无效。")
        label = max(probabilities, key=probabilities.get)
        emotion, review = map_label(label)
        path = resolve_project_path(rows[i][0], root=PROJECT_ROOT)
        existing[path] = EmotionSuggestionItem(audio_path=path.relative_to(PROJECT_ROOT),
            text_sha256=text_hash(rows[i][3]), suggested_emotion=emotion, raw_label=label,
            confidence=probabilities[label], requires_review=review)
    value = EmotionSuggestionFile(dataset_id=dataset_id, annotation_path=record.list_path.relative_to(PROJECT_ROOT),
        annotation_sha256=digest, model_id=classifier.config["model_id"],
        model_version=classifier.manifest["model_version"],
        items=[existing[p] for row in rows if (p := resolve_project_path(row[0], root=PROJECT_ROOT)) in existing])
    _publish(record, digest, value, previous_hash=previous_hash)
    return value


def apply_suggestions_to_rows(dataset_id, rows, *, high_confidence_only=True, protected_paths=()):
    with metadata_lock():
        record, _, digest = _snapshot(dataset_id)
        suggestions = load_suggestions(dataset_id)
        if suggestions is None:
            raise AppError("SUGGESTIONS_STALE", "建议不存在或文本已变化，请重新生成。")
        previous_hash = file_hash(_target(record))
        threshold = load_config(root=PROJECT_ROOT)["high_confidence_threshold"]
        by_path = {resolve_project_path(i.audio_path, root=PROJECT_ROOT): i for i in suggestions.items}
        protected = {resolve_project_path(p, root=PROJECT_ROOT) for p in protected_paths}
        original = {r[0]: r for r in dataset_service.load_corrections(dataset_id, dataset_service.DATASET_INDEX)}
        updated = [list(row) for row in rows]
        for row in updated:
            path = resolve_project_path(row[0], root=PROJECT_ROOT)
            item = by_path.get(path)
            if (not item or path in protected or item.accepted or record.status == "reviewed"
                    or row != original.get(row[0]) or text_hash(row[1]) != item.text_sha256):
                continue
            if item.requires_review or (high_confidence_only and item.confidence < threshold):
                continue
            row[2] = item.suggested_emotion
            item.accepted = True
        _publish(record, digest, suggestions, previous_hash=previous_hash)
        return updated


def suggestion_rows(dataset_id):
    if not dataset_id:
        return []
    try:
        value = load_suggestions(dataset_id)
        threshold = load_config(root=PROJECT_ROOT)["high_confidence_threshold"]
        return [[str(i.audio_path), i.suggested_emotion, i.raw_label, round(i.confidence, 4),
                 "已接受（待正式保存）" if i.accepted else "需复核" if i.requires_review or i.confidence < threshold else "模型建议",
                 "当前音色体系不支持，请人工选择" if i.requires_review else "置信度不足，请人工选择" if i.confidence < threshold else "文本语义建议"]
                for i in value.items] if value else []
    except (AppError, OSError):
        return []
