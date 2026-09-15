"""Run browser acceptance against the real app with isolated writable indexes."""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import inspect
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import audio_service, dataset_service, history_service, task_service, voice_service
from services.pipeline_service import PipelineRunner
from models.schemas import AppError, TaskRecord
from app import build_app


def main():
    with TemporaryDirectory(prefix="wgx-browser-") as directory, ExitStack() as stack:
        root = Path(directory).resolve()
        real_audio_mode = os.environ.get("AUDIO_SERVICE_SMOKE") == "1"
        index = root / "data" / "index"
        index.mkdir(parents=True)
        (index / "voices.json").write_text(voice_service.VOICE_INDEX.read_text(encoding="utf-8"), encoding="utf-8")
        mapping = {
            dataset_service.DATASET_INDEX: index / "datasets.json",
            dataset_service.DATASET_ROOT: root / "data" / "datasets",
            task_service.TASK_INDEX: index / "tasks.json",
            voice_service.VOICE_INDEX: index / "voices.json",
        }
        for module in (audio_service, dataset_service, task_service, voice_service):
            for function in vars(module).values():
                if inspect.isfunction(function) and function.__module__ == module.__name__:
                    if function.__defaults__:
                        stack.enter_context(patch.object(function, "__defaults__", tuple(mapping.get(value, value) if isinstance(value, Path) else value for value in function.__defaults__)))
                    if function.__kwdefaults__:
                        stack.enter_context(patch.object(function, "__kwdefaults__", {key: mapping.get(value, value) if isinstance(value, Path) else value for key, value in function.__kwdefaults__.items()}))
        stack.enter_context(patch.object(task_service, "PROJECT_ROOT", root))
        stack.enter_context(patch.object(audio_service, "PROJECT_ROOT", root))
        if not real_audio_mode:
            stack.enter_context(patch.object(audio_service, "_load_config", side_effect=AppError(
                "ENGINE_CONFIG_MISSING", "浏览器结构测试未配置模型环境。")))
        stack.enter_context(patch.object(task_service, "TASK_INDEX", index / "tasks.json"))
        stack.enter_context(patch.object(voice_service, "TASK_INDEX", index / "tasks.json"))
        stack.enter_context(patch.object(history_service, "HISTORY_INDEX", index / "history.json"))
        probe = PipelineRunner(root / "data" / "logs").run_stage(
            TaskRecord(task_id="wgx-negative-probe", kind="browser_engineering_probe"), "validating",
            [sys.executable, "-c", "raise SystemExit(7)"], cwd=root, outputs=[], gpu=False,
        )
        task_service.upsert_task(probe, index / "tasks.json")
        app = build_app()
        port = int(os.environ.get("WGX_SMOKE_PORT", "7861"))
        try:
            app.launch(server_name="127.0.0.1", server_port=port, prevent_thread_lock=True, quiet=True)
            env = dict(os.environ, WGX_SMOKE_URL=f"http://127.0.0.1:{port}", WGX_ISOLATED_BROWSER="1")
            browser_script = "audio_service_smoke.cjs" if real_audio_mode else "wgx_browser_smoke.cjs"
            completed = subprocess.run(["node", str(Path(__file__).with_name(browser_script))], env=env)
            if real_audio_mode:
                evidence = Path(__file__).resolve().parents[1] / "data/logs/audio-acceptance"
                evidence.mkdir(parents=True, exist_ok=True)
                for log in (root / "data/logs/audio").glob("*.log"):
                    shutil.copy2(log, evidence / log.name)
                records = dataset_service.list_datasets()
                tasks = [item for item in task_service.list_tasks() if item.kind == "process_audio"]
                (evidence / "records.json").write_text(json.dumps({
                    "datasets": [item.model_dump(mode="json") for item in records],
                    "tasks": [item.model_dump(mode="json") for item in tasks],
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                for record in records:
                    if record.list_path and record.list_path.is_file():
                        shutil.copy2(record.list_path, evidence / "asr.list")
            if completed.returncode:
                raise SystemExit(completed.returncode)
            if not real_audio_mode and env.get("WGX_REAL_AUDIO") and env.get("WGX_REAL_LIST"):
                datasets = dataset_service.list_datasets()
                assert len(datasets) == 1 and datasets[0].status == "reviewed"
                assert dataset_service.load_corrections(datasets[0].dataset_id)[0][2] == "sad"
                assert voice_service.get_voice("wgx-browser-only") is None
                print("Isolated correction persistence and no untrained voice: PASS")
        finally:
            app.close()


if __name__ == "__main__":
    main()
