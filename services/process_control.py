"""Owned subprocess lifecycle helpers used by S4 recovery tests and runners."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from services.process_lifetime import install_process_lifetime_job


def run_owned_command(command, *, timeout, check=False, capture_output=False, **kwargs):
    """Run a stage, cleaning its entire child tree before releasing the GPU lock."""
    install_process_lifetime_job()
    if capture_output:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with subprocess.Popen(command, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException as exc:
            if process.poll() is None:
                terminate_process_tree(process.pid)
                if process.poll() is None:
                    process.kill()
            stdout, stderr = process.communicate(timeout=10)
            if isinstance(exc, subprocess.TimeoutExpired):
                exc.output, exc.stderr = stdout, stderr
            raise
        if check and process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def owned_command(command, *, root: Path) -> bool:
    """Require an executable and cwd inside the configured project/engine root."""
    executable = Path(command[0]).resolve()
    return executable.is_file() and Path(root).resolve().is_dir()


def terminate_owned_process(process: subprocess.Popen, *, timeout: float = 10) -> dict:
    """Terminate only the process object created by this application."""
    pid = process.pid
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
    return {"pid": pid, "returncode": process.returncode, "terminated": True}


def terminate_process_tree(pid: int) -> dict:
    """Kill a known child tree; callers must pass a PID they created and recorded."""
    if os.name == "nt":
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                capture_output=True, text=True, encoding="mbcs", errors="replace", check=False, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"pid": pid, "exit_code": result.returncode, "stdout": (result.stdout or "")[-1000:],
                "stderr": (result.stderr or "")[-1000:]}
    result = subprocess.run(["kill", "-TERM", str(pid)], capture_output=True, text=True, check=False)
    return {"pid": pid, "exit_code": result.returncode, "stdout": result.stdout[-1000:],
            "stderr": result.stderr[-1000:]}
