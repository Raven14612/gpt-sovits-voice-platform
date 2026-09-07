from unittest import TestCase

from models.schemas import AppError, TaskRecord, TaskStatus
from services.task_service import run_gpu_task, transition


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
