from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from models.schemas import AppError, TaskRecord, TaskStatus
from services.task_service import list_tasks, recover_tasks, run_gpu_task, transition, upsert_task


class TaskServiceTests(TestCase):
    def test_valid_and_invalid_transitions(self):
        task = TaskRecord(task_id="t", kind="probe")
        running = transition(task, TaskStatus.RUNNING, stage="validating")
        self.assertEqual(running.status, TaskStatus.RUNNING)
        with self.assertRaises(AppError):
            transition(running, TaskStatus.PENDING)

    def test_gpu_task_reports_failure_and_releases_lock(self):
        task = TaskRecord(task_id="t", kind="gpu")
        result = run_gpu_task(task, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(run_gpu_task(task, lambda: None).status, TaskStatus.SUCCEEDED)

    def test_recover_running_tasks_marks_them_failed(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "tasks.json"
            upsert_task(TaskRecord(task_id="running-1", kind="train_voice", status=TaskStatus.RUNNING), index)
            upsert_task(TaskRecord(task_id="done-1", kind="train_voice", status=TaskStatus.SUCCEEDED), index)

            recovered = recover_tasks(index)

            self.assertEqual(len(recovered), 2)
            self.assertEqual(next(item for item in recovered if item.task_id == "running-1").status, TaskStatus.FAILED)
            self.assertEqual(next(item for item in recovered if item.task_id == "done-1").status, TaskStatus.SUCCEEDED)
            self.assertEqual(next(item for item in list_tasks(index) if item.task_id == "running-1").status, TaskStatus.FAILED)
