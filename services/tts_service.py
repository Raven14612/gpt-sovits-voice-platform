from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

from adapters import GPTSoVITSAdapter
from models.schemas import AppError, EngineConfig, GenerationRecord, TaskRecord, TaskStatus
from services import history_service
from services.task_service import release_gpu, try_acquire_gpu, upsert_task, transition
from services.voice_service import get_voice_profile
from services.wav_service import inspect_wav
from services.engine_service import load_engine_config

from services.project_paths import PROJECT_ROOT
LOCAL_CONFIG = PROJECT_ROOT / "config" / "engine.local.json"
LOG_ROOT = PROJECT_ROOT / "data" / "logs" / "synthesis"


def capabilities():
    return {"speed_factor": True, "fragment_interval": False, "fragment_interval_default": 0.3,
            "reason": "当前推理接口使用固定停顿，暂不支持调整。"}


def synthesize(*, voice_id: str, target_text: str, output_path: Path, emotion: str = "neutral",
               speed_factor: float = 1.0, fragment_interval: float = 0.3,
               refer_text: str | None = None, refer_wav: Path | None = None,
               port: int = 9888, timeout: int = 180, config_path: Path = LOCAL_CONFIG) -> Path:
    task_id = f"tts-task-{uuid4().hex}"
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = LOG_ROOT / f"{task_id}-synthesis.log"
    params = {"voice_id": voice_id, "text": str(target_text or "").strip(), "emotion": emotion,
              "speed_factor": speed_factor, "fragment_interval": fragment_interval}
    current = TaskRecord(task_id=task_id, kind="synthesis", stage="validating",
                         result_id=Path(output_path).stem, input_params=params, log_path=log_path)
    started = time.monotonic()
    acquired = False
    generated = False
    published = False
    output = None

    def log(event, **fields):
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event": event, "task_id": task_id,
                "elapsed_seconds": round(time.monotonic()-started, 3), **fields},
                ensure_ascii=False, default=str) + "\n")

    log("submitted", input_params=params, result_id=current.result_id)
    upsert_task(current)
    try:
        output = history_service.output_path(output_path)
        try:
            record = GenerationRecord(result_id=output.stem, output_path=output, **params)
        except ValueError as exc:
            raise AppError("INVALID_PARAMETER", "文本须为 1–500 字，语速为 0.5–2，情绪须有参考。", stage="validating") from exc
        if record.fragment_interval != 0.3:
            raise AppError("UNSUPPORTED_PARAMETER", capabilities()["reason"], stage="validating")
        if output.exists() or history_service.get_history(record.result_id):
            raise AppError("RESULT_CONFLICT", "结果已存在，请使用新结果 ID。", stage="validating")
        profile = get_voice_profile(voice_id)
        if profile is None or profile.status != "verified" or not profile.gpt_weight or not profile.sovits_weight:
            raise AppError("VOICE_WEIGHTS_MISSING", "未找到已验证音色档案。", stage="validating")
        reference = next((item for item in profile.references if item.emotion == emotion), None)
        if reference is None:
            raise AppError("REFERENCE_MISSING", f"音色缺少 {emotion} 参考音频。", stage="validating")
        wav = Path(refer_wav or reference.audio_path)
        text = (refer_text if refer_text is not None else reference.prompt_text).strip()
        if not wav.is_file() or not text:
            raise AppError("REFERENCE_MISSING", "参考音频或参考文本不可用。", stage="validating")
        try:
            config = load_engine_config(Path(config_path))
        except (OSError, ValueError) as exc:
            raise AppError("ENGINE_UNAVAILABLE", "模型配置无效，请检查本机配置。", stage="validating") from exc
        try_acquire_gpu(kind="synthesis")
        acquired = True
        latest = get_voice_profile(voice_id)
        if latest is None or latest.status != "verified" or latest != profile:
            raise AppError("VOICE_CHANGED", "音色组已变化，请重新选择。")
        record = record.model_copy(update={"source_snapshot": history_service.source_snapshot(voice_id, emotion, profile=profile, reference_path=wav, prompt_text=text)})
        current = transition(current, TaskStatus.RUNNING, stage="synthesis", message="正在生成语音")
        upsert_task(current)
        adapter = GPTSoVITSAdapter(config)
        log("running", reference=str(wav), prompt_text=text)
        result = adapter.synthesize(gpt_path=Path(profile.gpt_weight), sovits_path=Path(profile.sovits_weight),
            refer_wav=wav, refer_text=text, target_text=record.text, output_path=output,
            speed_factor=record.speed_factor, fragment_interval=record.fragment_interval, port=port, timeout=timeout)
        generated = True
        if Path(result).resolve() != output:
            raise AppError("OUTPUT_INVALID", "引擎返回路径与请求不一致。", stage="synthesis")
        info = inspect_wav(output)
        info.update(getattr(adapter, "last_inference", {}))
        if "weights" in info:
            info["weights"] = [Path(weight).name for weight in info["weights"]]
        info["output_path"] = output.relative_to(PROJECT_ROOT.resolve()).as_posix()
        log("output_validated", output_info=info)
        history_service.add_history(record.model_copy(update={"status": "succeeded"}))
        published = True
        current = current.model_copy(update={"output_info": info})
        upsert_task(transition(current, TaskStatus.SUCCEEDED, message="合成完成，结果已保存"))
        log("succeeded", result_id=record.result_id)
        return output
    except Exception as exc:
        if published:
            history_service.delete_history(current.result_id)
        elif generated and output:
            output.unlink(missing_ok=True)
        error = exc if isinstance(exc, AppError) else AppError("SYNTHESIS_FAILED", str(exc), stage="synthesis")
        current = current.model_copy(update={"error_code": error.code})
        upsert_task(transition(current, TaskStatus.FAILED, message=f"{error.code}：{error.message}"))
        log("failed", error_code=error.code, message=error.message)
        raise error from exc
    finally:
        if acquired:
            release_gpu()
