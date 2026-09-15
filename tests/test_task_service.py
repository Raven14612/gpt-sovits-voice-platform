from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from models.schemas import AppError, TaskRecord, TaskStatus
from services.task_service import list_tasks, recover_tasks, release_gpu, run_gpu_task, transition, try_acquire_gpu, upsert_task


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
            upsert_task(TaskRecord(task_id="pending-1", kind="train_voice"), index)

            recovered = recover_tasks(index)

            self.assertEqual(len(recovered), 3)
            self.assertEqual(next(item for item in recovered if item.task_id == "pending-1").status, TaskStatus.CANCELLED)
            self.assertEqual(next(item for item in recovered if item.task_id == "running-1").status, TaskStatus.FAILED)
            self.assertEqual(next(item for item in recovered if item.task_id == "done-1").status, TaskStatus.SUCCEEDED)
            self.assertEqual(next(item for item in list_tasks(index) if item.task_id == "running-1").status, TaskStatus.FAILED)

    def test_terminal_task_rejection_releases_gpu(self):
        for status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            with self.subTest(status=status):
                operation = Mock()
                try:
                    with self.assertRaises(AppError) as ctx:
                        run_gpu_task(TaskRecord(task_id="terminal", kind="gpu", status=status), operation)
                    self.assertEqual(ctx.exception.code, "INVALID_TASK_STATE")
                    operation.assert_not_called()
                    self.assertEqual(
                        run_gpu_task(TaskRecord(task_id="next", kind="gpu"), lambda: None).status,
                        TaskStatus.SUCCEEDED,
                    )
                finally:
                    release_gpu()

    def test_busy_rejection_does_not_release_active_gpu(self):
        operation = Mock()
        try_acquire_gpu()
        try:
            with self.assertRaises(AppError) as ctx:
                run_gpu_task(TaskRecord(task_id="busy", kind="gpu"), operation)
            self.assertEqual(ctx.exception.code, "GPU_BUSY")
            operation.assert_not_called()
            with self.assertRaises(AppError) as ctx:
                try_acquire_gpu()
            self.assertEqual(ctx.exception.code, "GPU_BUSY")
        finally:
            release_gpu()
