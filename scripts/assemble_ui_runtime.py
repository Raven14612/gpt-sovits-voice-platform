"""Build a relocatable Windows UI runtime from pinned CPython and hashed wheels."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    lock = json.loads((ROOT / "config/ui-runtime.lock.json").read_text(encoding="utf-8"))
    if os.name != "nt" or sys.version_info[:2] != (3, 13) or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Assembly requires Windows x64 Python 3.13 with pip. See README.md.")
    target = ROOT / "runtimes/ui"
    if target.exists():
        raise SystemExit("runtimes/ui already exists. Move it aside explicitly before rebuilding.")
    cache = ROOT / "data/cache/runtime-downloads"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / lock["filename"]
    if not archive.exists():
        with urllib.request.urlopen(lock["url"], timeout=60) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != lock["sha256"]:
        raise SystemExit("CPython archive checksum mismatch; preserved for inspection.")
    stage = ROOT / "runtimes" / ("ui-build-" + uuid4().hex)
    stage.mkdir(parents=True)
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            if not (stage / name).resolve().is_relative_to(stage.resolve()):
                raise ValueError("Invalid archive member")
        source.extractall(stage)
    subprocess.run([sys.executable, "-m", "pip", "install", "--only-binary=:all:",
        "--no-deps", "--require-hashes", "--no-compile", "--target", str(stage / "Lib/site-packages"),
        "-r", str(ROOT / "config/ui-requirements.lock")], check=True, cwd=ROOT, timeout=1200)
    (stage / "python313._pth").write_text("python313.zip\n.\nLib\\site-packages\n..\\..\nimport site\n", encoding="utf-8")
    subprocess.run([str(stage / "python.exe"), "-s", "-c",
        "import gradio,pydantic,yaml,ssl,numpy; print(gradio.__version__)"],
        check=True, cwd=stage, timeout=60)
    (stage / "assembly.json").write_text(json.dumps({"python": lock,
        "requirements_sha256": hashlib.sha256((ROOT / "config/ui-requirements.lock").read_bytes()).hexdigest(),
        "scope": "local UI runtime; model runtime remains separate"}, indent=2), encoding="utf-8")
    stage.rename(target)
    print(target)


if __name__ == "__main__":
    main()
