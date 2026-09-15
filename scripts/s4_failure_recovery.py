"""Controlled S4 evidence: child termination, restart recovery and process mutex."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services import task_service
from models.schemas import TaskRecord, TaskStatus


def main():
    evidence = ROOT / "data/logs/diagnostics/s4-failure-recovery"
    evidence.mkdir(parents=True, exist_ok=True)
    index = evidence / "tasks.json"
    task_service.upsert_task(TaskRecord(task_id="s4-crash-child", kind="s4-test",
                                        status=TaskStatus.RUNNING, stage="controlled_child"), index)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    time.sleep(.2)
    task_service.upsert_task(TaskRecord(task_id="s4-child-process", kind="s4-test",
                                        status=TaskStatus.RUNNING, stage="owned_child",
                                        input_params={"pid": child.pid}), index)
    child.terminate(); child.wait(timeout=10)
    recovered = task_service.recover_tasks(index)
    # Simulate the parent restart window: running records become failed, never success.
    assert any(item.task_id == "s4-child-process" and item.status == TaskStatus.FAILED for item in recovered)
    # Process-level mutex must reject a second interpreter.
    first = subprocess.Popen([sys.executable, "-c", "import time; from services import task_service; task_service.try_acquire_gpu(); time.sleep(3)"],
                             cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    time.sleep(.5)
    second = subprocess.run([sys.executable, "-c", "from services import task_service; task_service.try_acquire_gpu()"],
                            cwd=ROOT, capture_output=True, text=True)
    first.terminate(); first.wait(timeout=10)
    assert second.returncode != 0 and "GPU_BUSY" in second.stderr
    report = {"status": "passed", "owned_child_pid": child.pid, "mutex_second_exit": second.returncode,
              "recovered": [item.model_dump(mode="json") for item in recovered],
              "scope": "controlled child termination and restart state recovery"}
    (evidence / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
