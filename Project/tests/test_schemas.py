from pathlib import Path
from unittest import TestCase

from models.schemas import EngineConfig, TaskRecord, TaskStatus


class SchemaTests(TestCase):
    def test_engine_config_forces_serial_execution(self) -> None:
        config = EngineConfig(
            engine_root=Path("D:/engine"),
            python_path=Path("D:/engine/python.exe"),
            max_gpu_jobs=1,
            parallel_infer=False,
        )
        self.assertEqual(config.max_gpu_jobs, 1)
        self.assertFalse(config.parallel_infer)

    def test_task_starts_pending(self) -> None:
        task = TaskRecord(task_id="task-1", kind="probe")
        self.assertEqual(task.status, TaskStatus.PENDING)

