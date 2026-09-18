"""Optional loopback server owned by this desktop process; no external process takeover."""
from __future__ import annotations

import atexit
from pathlib import Path
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit

from models.schemas import AppError

_lock = threading.RLock()
_running = {}


def ensure_local_service(config, root):
    url = urlsplit(config["base_url"])
    if (not config.get("auto_start_local", False) or url.scheme != "http"
            or url.hostname not in ("127.0.0.1", "localhost")):
        return ""
    key = (str(Path(root).resolve()), url.port or 80)
    with _lock:
        current = _running.get(key)
        if current and current[1].is_alive() and current[0].started:
            return current[2]
        listener = socket.socket()
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", key[1]))
        except OSError:
            listener.close()
            return ""  # The client health check diagnoses an existing service.
        try:
            import uvicorn
            from workshop_server.app import create_app
            # Preserve legacy standalone data if it exists; never relocate it silently.
            legacy = Path(root) / "workshop_data"
            data = legacy if legacy.exists() else Path(root) / "data/workshop"
            token = secrets.token_urlsafe(32)
            server = uvicorn.Server(uvicorn.Config(
                create_app(data_dir=data, upload_token=token,
                           max_package_bytes=config["max_package_bytes"]),
                host="127.0.0.1", port=key[1], log_level="error", access_log=False))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]},
                                      daemon=True, name="local-workshop")
            thread.start()
            deadline = time.monotonic() + 5
            while thread.is_alive() and not server.started and time.monotonic() < deadline:
                time.sleep(.05)
            if not server.started:
                server.should_exit = True
                thread.join(timeout=2)
                raise OSError("local server did not start")
            _running[key] = (server, thread, token, listener)
            return token
        except Exception as exc:
            listener.close()
            raise AppError("WORKSHOP_START_FAILED", "本地工坊启动失败，请检查目录写入权限和 UI 运行时依赖。其他页面仍可使用。") from exc


def stop_local_services():
    with _lock:
        for server, thread, _, listener in _running.values():
            server.should_exit = True
            thread.join(timeout=3)
            listener.close()
        _running.clear()


atexit.register(stop_local_services)
