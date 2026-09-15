from __future__ import annotations

import json
import math
import re
import wave
from pathlib import Path
from typing import Mapping, Optional
from uuid import uuid4

from adapters import GPTSoVITSAdapter
from models.schemas import AppError, DatasetRecord, EngineConfig, TaskRecord, TaskStatus
from services.dataset_service import DATASET_INDEX, get_dataset, upsert_dataset, _read_transcript
from services.engine_service import LOCAL_CONFIG, load_engine_config
from services.pipeline_service import PipelineRunner
from services.task_service import TASK_INDEX, get_task, release_gpu, transition, try_acquire_gpu, upsert_task

from services.project_paths import PROJECT_ROOT


def _load_config(config_path: Path) -> EngineConfig:
    try:
        return load_engine_config(config_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AppError("ENGINE_CONFIG_MISSING", "模型环境配置无效或不存在。", stage="validating") from exc


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def process_audio(dataset: DatasetRecord, params: Optional[Mapping[str, object]] = None,
                  *, config_path: Path = LOCAL_CONFIG, task_index: Path = TASK_INDEX,
                  dataset_index: Path = DATASET_INDEX) -> TaskRecord:
    """Run real slicing and ASR through the configured external runtime."""
    params = params or {}
    task_id = str(params.get("task_id") or f"audio-{uuid4().hex}")
    if not re.fullmatch(r"audio-[a-zA-Z0-9-]{1,100}", task_id) or get_task(task_id, task_index):
        raise AppError("INVALID_TASK_ID", "音频任务 ID 无效或已存在。", stage="validating")
    try_acquire_gpu()
    current = None
    try:
        task = TaskRecord(task_id=task_id, kind="process_audio", stage="validating")
        upsert_task(task, task_index)
        current = transition(task, TaskStatus.RUNNING, message="检查原始音频和模型入口")
        upsert_task(current, task_index)
        record = get_dataset(dataset.dataset_id, dataset_index)
        if record is None:
            raise AppError("DATASET_MISSING", "数据集不存在，请重新选择。")
        config = _load_config(config_path)
        root = config.engine_root.resolve()
        adapter = GPTSoVITSAdapter(config)
        env = adapter.audio_environment()
        source = record.source_path.resolve()
        data_root = (PROJECT_ROOT / "data/datasets").resolve()
        if not _inside(source, data_root) or not source.is_file():
            raise AppError("INVALID_AUDIO", "原始音频必须位于项目数据集目录内。")
        start, end = _audio_bounds(source, params.get("start", 0), params.get("end"))
        timeout = int(params.get("timeout", 3600))
        if timeout <= 0:
            raise AppError("INVALID_TIMEOUT", "超时必须大于 0 秒。")
        # Each run gets new outputs; failure preserves the last accepted dataset revision.
        run_dir = source.parent / "processing" / task_id
        if not _inside(run_dir, data_root):
            raise AppError("OUTPUT_INVALID", "任务输出目录越界。")
        run_dir.mkdir(parents=True, exist_ok=False)
        slice_dir, asr_dir = run_dir / "slices", run_dir / "asr"
        slice_dir.mkdir()
        asr_dir.mkdir()
        log_dir = PROJECT_ROOT / "data/logs/audio"
        runner = PipelineRunner(log_dir)
        metadata = {"dataset_id": record.dataset_id, "source": str(source),
                    "start_frame": start, "end_frame": end, "task_id": task_id}
        (run_dir / "input.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        prepared = _crop_audio(source, run_dir / "input.wav", start, end)
        current = transition(current, TaskStatus.RUNNING, stage="slicing", message="开始语音切分",
                             log_path=log_dir / f"{task_id}-slicing.log")
        upsert_task(current, task_index)
        current = runner.run_stage(current, "slicing", adapter.slice_command(prepared, slice_dir),
                                   cwd=root, outputs=[], gpu=False, final=False, timeout=timeout, env=env)
        upsert_task(current, task_index)
        if current.status != TaskStatus.RUNNING:
            return current
        wavs = sorted(slice_dir.glob("*.wav"))
        if not wavs:
            raise AppError("OUTPUT_INVALID", "切分未生成任何 WAV 切片。", stage="slicing")
        for wav in wavs:
            if not _inside(wav, slice_dir):
                raise AppError("OUTPUT_INVALID", "切片路径越界。", stage="slicing")
            _audio_bounds(wav, 0, None)
        current = transition(current, TaskStatus.RUNNING, stage="asr", message=f"识别 {len(wavs)} 个切片",
                             log_path=log_dir / f"{task_id}-asr.log")
        upsert_task(current, task_index)
        transcript = asr_dir / "slices.list"
        current = runner.run_stage(current, "asr", adapter.asr_command(slice_dir, asr_dir),
                                   cwd=root, outputs=[transcript], gpu=False, final=False, timeout=timeout, env=env)
        upsert_task(current, task_index)
        if current.status != TaskStatus.RUNNING:
            return current
        validate_asr_coverage(transcript, wavs)
        upsert_dataset(record.model_copy(update={"slice_dir": slice_dir, "list_path": transcript,
                                                 "emotions_path": None, "feature_manifest": None,
                                                 "status": "transcribed"}), dataset_index)
        final = transition(current, TaskStatus.SUCCEEDED, stage="asr", message=f"已生成 {len(wavs)} 个切片和 ASR 标注")
        upsert_task(final, task_index)
        return final
    except Exception as exc:
        if current is None:
            raise
        message = f"{exc.code}：{exc.message}" if isinstance(exc, AppError) else str(exc)
        if current.log_path and current.log_path.is_file():
            with current.log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\nSERVICE CHECK: {message}\n")
        failed = transition(current, TaskStatus.FAILED, message=message)
        upsert_task(failed, task_index)
        return failed
    finally:
        release_gpu()


def _audio_bounds(path: Path, start, end):
    try:
        with wave.open(str(path), "rb") as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            start = float(start)
            end = frames / rate if end is None else float(end)
            if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= frames / rate):
                raise ValueError("裁剪范围必须位于音频时长内，终点必须大于起点。")
            # Check the declared payload is present, without loading the whole recording.
            audio.setpos(frames - 1)
            if len(audio.readframes(1)) != audio.getnchannels() * audio.getsampwidth():
                raise ValueError("WAV 数据不完整。")
            first, last = int(start * rate), min(frames, round(end * rate))
            if last <= first:
                raise ValueError("裁剪范围不足一个采样点。")
            return first, last
    except (OSError, EOFError, wave.Error, ValueError, TypeError, ZeroDivisionError) as exc:
        raise AppError("INVALID_AUDIO", f"PCM WAV 或裁剪范围无效：{exc}") from exc


def _crop_audio(source: Path, target: Path, start: int, end: int) -> Path:
    with wave.open(str(source), "rb") as audio:
        if start == 0 and end == audio.getnframes():
            return source
        with wave.open(str(target), "wb") as output:
            output.setparams(audio.getparams())
            audio.setpos(start)
            remaining = end - start
            while remaining:
                count = min(remaining, 65536)
                output.writeframes(audio.readframes(count))
                remaining -= count
    return target


def validate_asr_coverage(transcript: Path, wavs: list) -> None:
    if not _inside(transcript, wavs[0].parent.parent):
        raise AppError("ASR_FAILED", "识别标注路径越界。")
    rows = _read_transcript(transcript)
    actual = [Path(row[0]).resolve() for row in rows]
    expected = {wav.resolve() for wav in wavs}
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise AppError("ASR_FAILED", f"切片与标注不一一对应：{len(wavs)} 个切片，{len(rows)} 条标注。")
