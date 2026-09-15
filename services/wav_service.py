"""Validate the complete PCM payload, not just a RIFF header."""
from pathlib import Path
import hashlib
import wave

from models.schemas import AppError


def inspect_wav(path: Path) -> dict:
    try:
        with wave.open(str(path), "rb") as wav:
            channels, width, rate, frames = (wav.getnchannels(), wav.getsampwidth(),
                                             wav.getframerate(), wav.getnframes())
            if min(channels, width, rate, frames) <= 0:
                raise ValueError("empty PCM")
            remaining = frames
            while remaining:
                count = min(remaining, 65536)
                if len(wav.readframes(count)) != count * channels * width:
                    raise ValueError("truncated PCM")
                remaining -= count
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        return {"sample_rate": rate, "channels": channels, "sample_width": width,
                "frames": frames, "duration_seconds": frames / rate,
                "bytes": path.stat().st_size, "sha256": digest}
    except (OSError, EOFError, wave.Error, ValueError) as exc:
        raise AppError("OUTPUT_INVALID", "输出不是完整、可读取的 PCM WAV。", stage="synthesis") from exc
