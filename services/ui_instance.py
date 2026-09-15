"""Identify this workspace's running Gradio UI before reusing its port."""
import json
import os
from pathlib import Path
import urllib.request

from services.project_paths import PROJECT_ROOT


def instance_path(root, port):
    return Path(root) / "data/runtime" / f"ui-{port}.json"


def register(app_id, port, root=PROJECT_ROOT):
    path = instance_path(root, port)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps({"root": str(Path(root).resolve()), "port": port,
                                        "app_id": app_id, "pid": os.getpid()}), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def unregister(app_id, port, root=PROJECT_ROOT):
    path = instance_path(root, port)
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("app_id") == app_id:
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def running_url(port, root=PROJECT_ROOT):
    try:
        saved = json.loads(instance_path(root, port).read_text(encoding="utf-8"))
        if saved["port"] != port or Path(saved["root"]).resolve() != Path(root).resolve():
            return None
        url = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "/config", timeout=2) as response:
            config = json.loads(response.read(2 * 1024 * 1024))
        if saved.get("app_id") is not None and config.get("app_id") == saved["app_id"]:
            return url
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None
