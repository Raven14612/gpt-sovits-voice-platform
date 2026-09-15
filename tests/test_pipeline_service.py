from __future__ import annotations

import shutil
import sys
from pathlib import Path
from unittest import TestCase

from models.schemas import AppError, TaskRecord, TaskStatus
from services.pipeline_service import PipelineRunner, StagePlan
from services.task_service import release_gpu, try_acquire_gpu


class PipelineRunnerTests(TestCase):
    def setUp(self) -> None:
        self.root = (Path(__file__).resolve().parent / "_tmp_pipeline" / self._testMethodName).resolve()
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.script = self._write_stage_script()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_stage_script(self) -> Path:
        script = self.root / "stage_script.py"
        script.write_text(
            "\n".join(
                [
                    "from pathlib import Path",
                    "import sys",
                    "import time",
                    "",
                    "mode = sys.argv[1]",
                    "stage = sys.argv[2]",
                    "outputs = [Path(item) for item in sys.argv[3:]]",
                    'print("stdout:" + stage)',
                    'print("stderr:" + stage, file=sys.stderr)',
                    "if mode == 'sleep':",
                    "    time.sleep(2)",
                    "elif mode == 'fail':",
                    "    raise SystemExit(3)",
                    "elif mode != 'skip':",
                    "    for item in outputs:",
                    "        item.parent.mkdir(parents=True, exist_ok=True)",
                    "        item.write_text(stage, encoding='utf-8')",
                ]
            ),
            encoding="utf-8",
        )
        return script

    def _plan(
        self,
        stage: str,
        mode: str,
        *,
        outputs: list[Path],
        timeout: int = 5,
        gpu: bool = False,
    ) -> StagePlan:
        command = [sys.executable, str(self.script), mode, stage] + [str(item) for item in outputs]
        return StagePlan(
            stage=stage,
            command=command,
            cwd=self.root,
            outputs=outputs,
            timeout=timeout,
            gpu=gpu,
        )

    def test_six_stage_pipeline_runs_successfully(self) -> None:
        runner = PipelineRunner(self.root / "logs")
        stages = [
            self._plan("validating", "success", outputs=[self.root / "out" / "validating.txt"]),
            self._plan("slicing", "success", outputs=[self.root / "out" / "slicing.txt"]),
            self._plan("asr", "success", outputs=[self.root / "out" / "asr.txt"]),
            self._plan("feature_text", "success", outputs=[self.root / "out" / "feature_text.txt"]),
            self._plan("feature_hubert", "success", outputs=[self.root / "out" / "feature_hubert.txt"]),
            self._plan("feature_semantic", "success", outputs=[self.root / "out" / "feature_semantic.txt"]),
        ]

        task = runner.run_pipeline(TaskRecord(task_id="task-1", kind="dataset"), stages)

        self.assertEqual(task.status, TaskStatus.SUCCEEDED)
        self.assertEqual(task.stage, "feature_semantic")
        for plan in stages:
            self.assertTrue((self.root / "logs" / f"task-1-{plan.stage}.log").is_file())
            for output in plan.outputs:
                self.assertTrue(output.is_file())

    def test_pipeline_stops_after_failed_stage(self) -> None:
        runner = PipelineRunner(self.root / "logs")
        stages = [
            self._plan("validating", "success", outputs=[self.root / "out" / "validating.txt"]),
            self._plan("slicing", "fail", outputs=[]),
            self._plan("asr", "success", outputs=[self.root / "out" / "asr.txt"]),
            self._plan("feature_text", "success", outputs=[self.root / "out" / "feature_text.txt"]),
            self._plan("feature_hubert", "success", outputs=[self.root / "out" / "feature_hubert.txt"]),
            self._plan("feature_semantic", "success", outputs=[self.root / "out" / "feature_semantic.txt"]),
        ]

        task = runner.run_pipeline(TaskRecord(task_id="task-8", kind="dataset"), stages)

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.stage, "slicing")
        self.assertTrue((self.root / "out" / "validating.txt").is_file())
        self.assertFalse((self.root / "out" / "asr.txt").exists())

    def test_pipeline_rejects_wrong_stage_order(self) -> None:
        runner = PipelineRunner(self.root / "logs")
        stages = [
            self._plan("slicing", "success", outputs=[self.root / "out" / "slicing.txt"]),
            self._plan("validating", "success", outputs=[self.root / "out" / "validating.txt"]),
            self._plan("asr", "success", outputs=[self.root / "out" / "asr.txt"]),
            self._plan("feature_text", "success", outputs=[self.root / "out" / "feature_text.txt"]),
            self._plan("feature_hubert", "success", outputs=[self.root / "out" / "feature_hubert.txt"]),
            self._plan("feature_semantic", "success", outputs=[self.root / "out" / "feature_semantic.txt"]),
        ]

        with self.assertRaises(AppError) as ctx:
            runner.run_pipeline(TaskRecord(task_id="task-10", kind="dataset"), stages)

        self.assertEqual(ctx.exception.code, "INVALID_STAGE_SEQUENCE")
        self.assertFalse((self.root / "logs").exists() and any((self.root / "logs").iterdir()))
        self.assertFalse((self.root / "out" / "slicing.txt").exists())

    def test_non_zero_exit_fails_and_keeps_stage(self) -> None:
        runner = PipelineRunner(self.root / "logs")
        task = runner.run_stage(
            TaskRecord(task_id="task-2", kind="dataset"),
            "validating",
            [sys.executable, str(self.script), "fail", "validating"],
            cwd=self.root,
            outputs=[],
            timeout=5,
            gpu=False,
        )
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.stage, "validating")
        self.assertNotEqual(task.status, TaskStatus.SUCCEEDED)

    def test_timeout_fails_and_records_log(self) -> None:
        runner = PipelineRunner(self.root / "logs")
        task = runner.run_stage(
            TaskRecord(task_id="task-3", kind="dataset"),
            "slicing",
            [sys.executable, str(self.script), "sleep", "slicing"],
            cwd=self.root,
            outputs=[],
            timeout=1,
            gpu=False,
        )
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.stage, "slicing")
        self.assertTrue(task.log_path.is_file())

    def test_output_missing_fails(self) -> None:
        runner = PipelineRunner(self.root / "logs")
        task = runner.run_stage(
            TaskRecord(task_id="task-4", kind="dataset"),
            "feature_text",
            [sys.executable, str(self.script), "skip", "feature_text"],
            cwd=self.root,
            outputs=[self.root / "missing" / "feature_text.txt"],
            timeout=5,
            gpu=False,
        )
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.stage, "feature_text")
        self.assertNotEqual(task.status, TaskStatus.SUCCEEDED)

    def test_output_directory_does_not_count_as_success(self) -> None:
        runner = PipelineRunner(self.root / "logs")
        output_dir = self.root / "out" / "feature_text.txt"
        output_dir.mkdir(parents=True, exist_ok=True)
        task = runner.run_stage(
            TaskRecord(task_id="task-9", kind="dataset"),
            "feature_text",
            [sys.executable, str(self.script), "skip", "feature_text", str(output_dir)],
            cwd=self.root,
            outputs=[output_dir],
            timeout=5,
            gpu=False,
        )
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.stage, "feature_text")
        self.assertNotEqual(task.status, TaskStatus.SUCCEEDED)

    def test_log_records_stdout_stderr_and_exit_code(self) -> None:
        runner = PipelineRunner(self.root / "logs")
        task = runner.run_stage(
            TaskRecord(task_id="task-5", kind="dataset"),
            "feature_hubert",
            [sys.executable, str(self.script), "success", "feature_hubert", str(self.root / "out" / "feature_hubert.txt")],
            cwd=self.root,
            outputs=[self.root / "out" / "feature_hubert.txt"],
            timeout=5,
            gpu=False,
        )
        log_path = task.log_path
        self.assertIsNotNone(log_path)
        self.assertTrue(log_path.is_file())
        content = log_path.read_text(encoding="utf-8")
        self.assertIn("COMMAND:", content)
        self.assertIn("stdout:feature_hubert", content)
        self.assertIn("stderr:feature_hubert", content)
        self.assertIn("EXIT CODE: 0", content)

    def test_intermediate_stage_stays_running_until_final_stage(self) -> None:
        runner = PipelineRunner(self.root / "logs")
        stage1 = runner.run_stage(
            TaskRecord(task_id="task-7", kind="dataset"),
            "validating",
            [sys.executable, str(self.script), "success", "validating", str(self.root / "out" / "validating.txt")],
            cwd=self.root,
            outputs=[self.root / "out" / "validating.txt"],
            timeout=5,
            gpu=False,
            final=False,
        )
        self.assertEqual(stage1.status, TaskStatus.RUNNING)
        self.assertEqual(stage1.stage, "validating")

        stage2 = runner.run_stage(
            stage1,
            "asr",
            [sys.executable, str(self.script), "success", "asr", str(self.root / "out" / "asr.txt")],
            cwd=self.root,
            outputs=[self.root / "out" / "asr.txt"],
            timeout=5,
            gpu=False,
            final=True,
        )
        self.assertEqual(stage2.status, TaskStatus.SUCCEEDED)
        self.assertEqual(stage2.stage, "asr")

    def test_gpu_busy_is_reported(self) -> None:
        runner = PipelineRunner(self.root / "logs")
        try:
            try_acquire_gpu()
            task = runner.run_stage(
                TaskRecord(task_id="task-6", kind="dataset"),
                "feature_semantic",
                [sys.executable, str(self.script), "success", "feature_semantic", str(self.root / "out" / "feature_semantic.txt")],
                cwd=self.root,
                outputs=[self.root / "out" / "feature_semantic.txt"],
                timeout=5,
                gpu=True,
            )
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertEqual(task.stage, "feature_semantic")
            self.assertIsNotNone(task.log_path)
            self.assertTrue(task.log_path.is_file())
            self.assertIn("GPU_BUSY", task.log_path.read_text(encoding="utf-8"))
        finally:
            release_gpu()
