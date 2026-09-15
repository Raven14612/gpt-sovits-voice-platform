from __future__ import annotations

import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import List, Optional

from adapters.base import SpeechEngineAdapter
from models.schemas import AppError, EngineStatus
from services.project_paths import PROJECT_ROOT, project_environment


class GPTSoVITSAdapter(SpeechEngineAdapter):
    """Configurable adapter. Week 1 only implements safe environment probing."""

    def audio_environment(self) -> dict:
        root = self.config.engine_root.resolve()
        python = self.config.python_path.resolve()
        for item in (python, root / "tools/slice_audio.py", root / "tools/asr/funasr_asr.py"):
            if not item.is_file():
                raise AppError("ENGINE_UNAVAILABLE", f"模型入口不存在：{item}", stage="validating")
        env = project_environment(python=python, engine_root=root)
        env["CUDA_VISIBLE_DEVICES"] = "0"
        return env

    def slice_command(self, source: Path, output: Path) -> List[str]:
        return [str(self.config.python_path.resolve()), "-s", "tools/slice_audio.py",
                str(source.resolve()), str(output.resolve()),
                "-34", "4000", "300", "10", "500", "0.9", "0.25", "0", "1"]

    def asr_command(self, slices: Path, output: Path) -> List[str]:
        return [str(self.config.python_path.resolve()), "-s", "tools/asr/funasr_asr.py",
                "-i", str(slices.resolve()), "-o", str(output.resolve()),
                "-s", "large", "-l", "zh", "-p", "float32"]

    def feature_environment(self, transcript: Path, slices: Path, output: Path) -> dict:
        """v2Pro single-GPU parameters verified against the external WebUI."""
        root = self.config.engine_root.resolve()
        env = self.audio_environment()
        assets = {
            "bert_pretrained_dir": "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large",
            "cnhubert_base_dir": "GPT_SoVITS/pretrained_models/chinese-hubert-base",
            "sv_path": "GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt",
            "pretrained_s2G": "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth",
            "s2config_path": "GPT_SoVITS/configs/s2v2Pro.json",
        }
        for key, relative in assets.items():
            path = root / relative
            if not path.exists():
                raise AppError("ENGINE_UNAVAILABLE", f"特征提取依赖不存在：{path}")
            env[key] = str(path)
        env.update(inp_text=str(transcript.resolve()), inp_wav_dir=str(slices.resolve()),
                   opt_dir=str(output.resolve()), exp_name=output.name, i_part="0", all_parts="1",
                   _CUDA_VISIBLE_DEVICES="0", is_half="True", version="v2Pro")
        env["PYTHONPATH"] = os.pathsep.join([str(root), str(root / "GPT_SoVITS"), env.get("PYTHONPATH", "")])
        return env

    def feature_command(self, stage: str) -> List[str]:
        entries = {"feature_text": "1-get-text.py", "feature_hubert": "2-get-hubert-wav32k.py",
                   "feature_sv": "2-get-sv.py", "feature_semantic": "3-get-semantic.py"}
        entry = self.config.engine_root.resolve() / "GPT_SoVITS/prepare_datasets" / entries[stage]
        if not entry.is_file():
            raise AppError("ENGINE_UNAVAILABLE", f"特征入口不存在：{entry}", stage=stage)
        return [str(self.config.python_path.resolve()), "-s", str(entry)]

    def probe_environment(self) -> EngineStatus:
        root = Path(self.config.engine_root).expanduser()
        python = Path(self.config.python_path).expanduser()
        missing: List[str] = []

        if not root.is_dir():
            missing.append("engine_root")
        if not python.is_file():
            missing.append("python_path")

        if missing:
            return EngineStatus(
                configured=False,
                available=False,
                message=f"缺少或无效配置：{', '.join(missing)}",
            )

        command = [
            str(python),
            "-c",
            (
                "import sys; "
                "print(sys.version.split()[0]); "
                "import torch; "
                "print(torch.__version__); "
                "print(torch.version.cuda); "
                "print(torch.cuda.is_available()); "
                "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
            ),
        ]

        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=project_environment(python=python, engine_root=root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return EngineStatus(
                configured=True,
                available=False,
                message=f"环境探测失败：{exc}",
            )

        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if completed.returncode != 0 or len(lines) < 5:
            detail = completed.stderr.strip() or completed.stdout.strip() or "无输出"
            return EngineStatus(
                configured=True,
                available=False,
                message=f"模型运行时不可用：{detail[-500:]}",
            )

        return EngineStatus(
            configured=True,
            available=lines[3].lower() == "true",
            python_version=lines[0],
            torch_version=lines[1],
            cuda_version=lines[2],
            gpu_name=lines[4],
            message="GPU 运行时可用" if lines[3].lower() == "true" else "Torch 未检测到 GPU",
        )

    def api_command(self, *, gpt_path: Path, sovits_path: Path, refer_wav: Path,
                    refer_text: str, target_text: str, port: int = 9888) -> List[str]:
        """Build the verified API server command; execution remains caller-controlled."""
        root = Path(self.config.engine_root).expanduser().resolve()
        python = Path(self.config.python_path).expanduser().resolve()
        for path, name in ((gpt_path, "gpt_path"), (sovits_path, "sovits_path"), (refer_wav, "refer_wav")):
            resolved = Path(path).expanduser().resolve()
            if not resolved.is_file():
                raise AppError("VOICE_WEIGHTS_MISSING" if "path" in name else "REFERENCE_MISSING", f"{name} 不存在。", stage="synthesis")
        if not refer_text.strip() or not target_text.strip():
            raise AppError("REFERENCE_MISSING", "参考文本和目标文本不能为空。", stage="synthesis")
        return [str(python), "-s", "api.py", "-s", str(sovits_path), "-g", str(gpt_path),
                "-dr", str(refer_wav), "-dt", refer_text, "-dl", "zh", "-a", "127.0.0.1", "-p", str(port), "-d", "cuda", "-sm", "close", "-mt", "wav"]

    def synthesize(self, *, gpt_path: Path, sovits_path: Path, refer_wav: Path,
                   refer_text: str, target_text: str, output_path: Path,
                   speed_factor: float = 1.0, fragment_interval: float = 0.3, port: int = 9888,
                   timeout: int = 180) -> Path:
        from adapters.inference_runtime import runtime
        from services.wav_service import inspect_wav
        if fragment_interval != 0.3:
            raise AppError("UNSUPPORTED_PARAMETER", "当前 api.py 不支持调整句间停顿。", stage="synthesis")
        command = self.api_command(gpt_path=gpt_path, sovits_path=sovits_path,
                                   refer_wav=refer_wav, refer_text=refer_text,
                                   target_text=target_text, port=port)
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(".wav.part")
        if output_path.exists() or temporary.exists():
            raise AppError("RESULT_CONFLICT", "输出路径已存在，请使用新的结果 ID。", stage="synthesis")
        deadline = time.monotonic() + timeout
        try:
            self.last_inference = runtime.ensure(self, command,
                (str(gpt_path.resolve()), str(sovits_path.resolve())), port, deadline,
                PROJECT_ROOT / "data/logs/synthesis")
            payload = {"refer_wav_path": str(refer_wav.resolve()), "prompt_text": refer_text,
                       "prompt_language": "zh", "text": target_text, "text_language": "zh",
                       "speed": speed_factor, "cut_punc": "。！？", "top_k": 15,
                       "top_p": 1.0, "temperature": 1.0, "inp_refs": []}
            temporary.write_bytes(runtime.request(port, "/", payload, deadline-time.monotonic()))
            inspect_wav(temporary)
            os.replace(temporary, output_path)
            return output_path
        except AppError:
            runtime.close()
            raise
        except (OSError, ValueError, urllib.error.URLError) as exc:
            runtime.close()
            code = "ENGINE_TIMEOUT" if isinstance(exc, (TimeoutError, socket.timeout)) else "SYNTHESIS_FAILED"
            raise AppError(code, f"推理请求失败：{exc}", stage="synthesis") from exc
        finally:
            temporary.unlink(missing_ok=True)
