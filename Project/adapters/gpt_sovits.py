from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List

from adapters.base import SpeechEngineAdapter
from models.schemas import EngineStatus


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
