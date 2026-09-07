from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from models.schemas import TaskRecord, TaskStatus
from services.pipeline_service import PipelineRunner


class PipelineRunnerTests(TestCase):
    def test_subprocess_failure_is_recorded(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = PipelineRunner(root / "logs").run_stage(
                TaskRecord(task_id="t", kind="stage"), "validating",
                ["python", "-c", "raise SystemExit(3)"], cwd=root, outputs=[], gpu=False,
            )
            self.assertEqual(result.status, TaskStatus.FAILED)

    def test_output_missing_fails(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = PipelineRunner(root / "logs").run_stage(
                TaskRecord(task_id="t", kind="stage"), "feature_text",
                ["python", "-c", "pass"], cwd=root, outputs=[root / "missing"], gpu=False,
            )
            self.assertEqual(result.status, TaskStatus.FAILED)
