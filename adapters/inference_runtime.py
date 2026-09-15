"""One owned loopback API process, shared by adapter instances in this app."""
from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from threading import RLock

from models.schemas import AppError
from services.process_lifetime import install_process_lifetime_job


class InferenceRuntime:
    def __init__(self):
        self.process = None
        self.key = None
        self.weights = None
        self.log_path = None
        self._lock = RLock()
        self._http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def close(self):
        with self._lock:
            process = self.process
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            # Retain ownership if termination fails so a later close can retry.
            self.process = self.key = self.weights = None

    def request(self, port, endpoint, payload=None, timeout=10):
        if timeout <= 0:
            raise AppError("ENGINE_TIMEOUT", "推理请求已超过截止时间。", stage="synthesis")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{port}{endpoint}", data=data,
                                     headers={"Content-Type": "application/json"})
        with self._http.open(req, timeout=max(0.1, timeout)) as response:
            return response.read()

    def ensure(self, adapter, command, weights, port, deadline, log_dir):
        with self._lock:
            try:
                return self._ensure(adapter, command, weights, port, deadline, log_dir)
            except BaseException:
                self.close()
                raise

    def _ensure(self, adapter, command, weights, port, deadline, log_dir):
        key = (str(adapter.config.engine_root.resolve()), str(adapter.config.python_path.resolve()), port)
        with self._lock:
            if self.process is not None and (self.process.poll() is not None or self.key != key):
                self.close()
            if self.process is None:
                install_process_lifetime_job()
                # Never send model paths or text to a process we did not start.
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", port)) == 0:
                        raise AppError("ENGINE_PORT_BUSY", f"推理端口 {port} 已被另一个进程占用。请关闭其他正在运行的推理服务后重试；平台不会自动终止未知进程。", stage="synthesis")
                log_dir.mkdir(parents=True, exist_ok=True)
                self.log_path = log_dir / f"engine-{time.time_ns()}.log"
                with self.log_path.open("w", encoding="utf-8") as log:
                    log.write("COMMAND: " + json.dumps(command, ensure_ascii=False) + "\n")
                    log.flush()
                    self.process = subprocess.Popen(command, cwd=adapter.config.engine_root,
                        stdout=log, stderr=subprocess.STDOUT, env=adapter.audio_environment(),
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.key = key
                self.weights = weights
                while True:
                    if self.process.poll() is not None:
                        raise AppError("ENGINE_EXITED", "推理进程启动时退出，请查看引擎日志。", stage="synthesis")
                    if time.monotonic() >= deadline:
                        raise AppError("ENGINE_TIMEOUT", "推理服务启动超时。", stage="synthesis")
                    try:
                        self.request(port, "/openapi.json", timeout=min(2, deadline-time.monotonic()))
                        break
                    except (urllib.error.URLError, TimeoutError, ConnectionError):
                        time.sleep(0.25)
            else:
                self.request(port, "/openapi.json", timeout=min(5, deadline-time.monotonic()))
            if self.weights != weights:
                response = json.loads(self.request(port, "/set_model", {
                    "gpt_model_path": weights[0], "sovits_model_path": weights[1]},
                    timeout=deadline-time.monotonic()))
                if response.get("code") != 0:
                    raise AppError("VOICE_WEIGHTS_MISSING", "引擎拒绝加载音色权重。", stage="synthesis")
                self.weights = weights
            return {"engine_pid": self.process.pid,
                    "engine_log": self.log_path.name, "weights": list(weights)}


runtime = InferenceRuntime()
atexit.register(runtime.close)
