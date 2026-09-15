"""Package entry point; stdlib checks run before Gradio or model imports."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import traceback
import webbrowser
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.project_paths import project_environment, resolve_project_path
from services.ui_instance import running_url


def preflight(port=7860):
    expected_ui = ROOT / "runtimes/ui/python.exe"
    if Path(sys.executable).resolve() != expected_ui.resolve():
        raise ValueError("Use start.bat with the package UI interpreter.")
    raw = json.loads((ROOT / "config/engine.local.json").read_text(encoding="utf-8"))
    engine = resolve_project_path(raw["engine_root"], root=ROOT)
    python = resolve_project_path(raw["python_path"], root=ROOT)
    for path in (engine, python):
        if not path.is_relative_to(ROOT) or not path.exists():
            raise ValueError(f"Configured engine/runtime missing or outside this package: {path}")
    if python == expected_ui:
        raise ValueError("The UI and model interpreters must be separate.")
    env = project_environment(root=ROOT, python=python, engine_root=engine)
    probe = subprocess.run([str(python), "-s", "-c",
        "import sys,json; print(json.dumps({'executable':sys.executable,'prefix':sys.prefix}))"],
        cwd=engine, env=env, timeout=30, capture_output=True, text=True, encoding="utf-8", check=True)
    runtime = json.loads(probe.stdout)
    if Path(runtime["executable"]).resolve() != python:
        raise ValueError("Engine interpreter resolved to an unexpected location.")
    with socket.socket() as listener:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            raise ValueError(f"Port {port} is already in use. Close its owner or use --port.") from exc
    return {"project_root": str(ROOT), "ui_python": sys.executable,
            "engine_root": str(engine), "engine_python": runtime, "port": port,
            "scope": "paths_and_interpreters_only"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--check", action="store_true", help="Check paths and interpreters without starting UI")
    parser.add_argument("--diagnose", action="store_true", help="Run full S5 diagnostics without starting UI")
    args = parser.parse_args()
    try:
        if not args.check and not args.diagnose:
            existing = running_url(args.port, ROOT)
            if existing:
                print(f"平台已在运行，正在打开：{existing}", flush=True)
                if not webbrowser.open(existing):
                    print(f"请在浏览器打开：{existing}", flush=True)
                return 0
        from services.process_lifetime import install_process_lifetime_job
        install_process_lifetime_job()
        from setup.EnvironmentSetup.env_setup.checker import run_check
        if args.diagnose:
            diagnostics = run_check(ROOT, ui_port=args.port)
            print(json.dumps({"summary": diagnostics["summary"], "levels": diagnostics["levels"]}, ensure_ascii=False))
            return 1 if diagnostics["summary"] == "FAIL" else 0
        report = preflight(args.port)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if args.check:
            return 0
        # Startup diagnoses dependencies and file presence without allocating GPU memory.
        # Full content hashes and CUDA execution remain explicit in --diagnose/setup.
        diagnostics = run_check(ROOT, ui_port=args.port, include_gpu=False, verify_hashes=False,
                               report_path=ROOT / "data/logs/startup-environment.json")
        print(json.dumps({"environment": diagnostics["levels"],
                          "report": "data/logs/startup-environment.json"}, ensure_ascii=False), flush=True)
        basic_failures = [item for item in diagnostics["checks"]
                          if "base" in item["groups"] and item["status"] == "FAIL"]
        if basic_failures:
            raise ValueError("UI startup checks failed: " + ", ".join(item["key"] for item in basic_failures)
                             + "; run setup/EnvironmentSetup/start.bat for details")
        os.chdir(ROOT)
        env = project_environment(root=ROOT, python=sys.executable, engine_root=report["engine_root"])
        for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE"):
            os.environ.pop(key, None)
        os.environ.update(env)
        import app
        app.main(port=args.port)
        return 0
    except Exception as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        try:
            log = ROOT / "data/logs/launcher-error.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as stream:
                stream.write(f"\n{datetime.now(timezone.utc).isoformat()}\n{traceback.format_exc()}\n")
            print(f"Error log: {log}", file=sys.stderr)
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
