from __future__ import annotations

import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional

from adapters.base import SpeechEngineAdapter
from models.schemas import AppError, EngineStatus


class GPTSoVITSAdapter(SpeechEngineAdapter):
    """Configurable adapter. Week 1 only implements safe environment probing."""

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
                "-dr", str(refer_wav), "-dt", refer_text, "-dl", "zh", "-p", str(port)]

    def synthesize(self, *, gpt_path: Path, sovits_path: Path, refer_wav: Path,
                   refer_text: str, target_text: str, output_path: Path,
                   port: int = 9888, timeout: int = 180) -> Path:
        """Run the verified API server and save one real WAV output."""
        command = self.api_command(gpt_path=gpt_path, sovits_path=sovits_path,
                                    refer_wav=refer_wav, refer_text=refer_text,
                                    target_text=target_text, port=port)
        log_path = output_path.with_suffix(".log")
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=self.config.engine_root,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       text=True)
        try:
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    query = urllib.parse.urlencode({"text": target_text, "text_language": "zh"})
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/?{query}", timeout=timeout) as response:
                        output_path.write_bytes(response.read())
                    if output_path.stat().st_size < 44:
                        raise AppError("OUTPUT_INVALID", "合成输出不是有效 WAV。", stage="synthesis")
                    return output_path
                except (urllib.error.URLError, ConnectionError):
                    time.sleep(1)
            raise AppError("SYNTHESIS_FAILED", "合成服务在限定时间内未响应。", stage="synthesis")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
