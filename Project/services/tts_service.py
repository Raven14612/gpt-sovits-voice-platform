from __future__ import annotations
import json
from pathlib import Path
from adapters import GPTSoVITSAdapter
from models.schemas import AppError, EngineConfig
from services.task_service import release_gpu, try_acquire_gpu
from services.voice_service import get_voice_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = PROJECT_ROOT / "config" / "engine.local.json"

def synthesize(*, voice_id: str, target_text: str, output_path: Path,
               emotion: str = "neutral", speed_factor: float = 1.0,
               fragment_interval: float = 0.3,
               refer_text: str | None = None, refer_wav: Path | None = None,
               port: int = 9888, timeout: int = 180,
               config_path: Path = LOCAL_CONFIG) -> Path:
    profile = get_voice_profile(voice_id)
    if profile is None or profile.status != "verified":
        raise AppError("VOICE_WEIGHTS_MISSING", "未找到已验证音色档案。", stage="synthesis")
    reference = next((item for item in profile.references if item.emotion == emotion), None)
    if reference is None:
        raise AppError("REFERENCE_MISSING", f"音色缺少 {emotion} 参考音频。", stage="synthesis")
    wav = Path(refer_wav or (reference.audio_path if reference else ""))
    text = (refer_text or reference.prompt_text).strip()
    if not wav.is_file():
        raise AppError("REFERENCE_MISSING", "缺少有效参考音频。", stage="synthesis")
    if not text or not str(target_text).strip():
        raise AppError("REFERENCE_MISSING", "参考文本和目标文本不能为空。", stage="synthesis")
    try:
        config = EngineConfig.model_validate(json.loads(Path(config_path).read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AppError("ENGINE_UNAVAILABLE", f"模型配置无效：{exc}", stage="synthesis") from exc
    if not 0.5 <= float(speed_factor) <= 2.0 or not 0.0 <= float(fragment_interval) <= 2.0:
        raise AppError("INVALID_PARAMETER", "语速或句间停顿超出允许范围。", stage="synthesis")
    try_acquire_gpu()
    try:
        return GPTSoVITSAdapter(config).synthesize(
            gpt_path=Path(profile.gpt_weight), sovits_path=Path(profile.sovits_weight),
            refer_wav=wav, refer_text=text, target_text=target_text,
            output_path=Path(output_path), speed_factor=float(speed_factor),
            port=port, timeout=timeout)
    finally:
        release_gpu()
