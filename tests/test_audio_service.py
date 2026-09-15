import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from models.schemas import AppError, DatasetRecord, TaskStatus
from services import audio_service, dataset_service, task_service


class AudioServiceTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.engine = self.root / "engine"
        for name in ("tools/slice_audio.py", "tools/asr/funasr_asr.py"):
            entry = self.engine / name
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.touch()
        self.config = self.root / "engine.json"
        self.config.write_text(json.dumps({"engine_root": str(self.engine), "python_path": sys.executable}), encoding="utf-8")
        self.index = self.root / "datasets.json"
        self.tasks = self.root / "tasks.json"
        self.source = self.root / "data/datasets/test/source.wav"
        self.source.parent.mkdir(parents=True)
        self.dataset = DatasetRecord(dataset_id="test", display_name="test", source_path=self.source)
        dataset_service.upsert_dataset(self.dataset, self.index)
        self.scope = patch.object(audio_service, "PROJECT_ROOT", self.root)
        self.scope.start()
        self.addCleanup(self.scope.stop)

    def real_audio(self):
        source = os.environ.get("GPT_SOVITS_REAL_AUDIO")
        if not source or not Path(source).is_file():
            self.skipTest("real audio fixture unavailable")
        shutil.copy2(source, self.source)

    def run_audio(self, **params):
        return audio_service.process_audio(self.dataset, params, config_path=self.config,
                                           task_index=self.tasks, dataset_index=self.index)

    def command_result(self, command, **kwargs):
        self.assertEqual(kwargs["cwd"], self.engine)
        self.assertEqual(kwargs["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertTrue(kwargs["env"]["PATH"].startswith(str(Path(sys.executable).parent)))
        self.assertTrue(task_service.is_gpu_busy())
        if command[2] == "tools/slice_audio.py":
            self.assertEqual(command[5:], ["-34", "4000", "300", "10", "500", "0.9", "0.25", "0", "1"])
            for name in ("first.wav", "second.wav"):
                shutil.copy2(command[3], Path(command[4]) / name)
        else:
            self.assertEqual(command[2], "tools/asr/funasr_asr.py")
            slices, output = Path(command[4]), Path(command[6])
            (output / "slices.list").write_text("\n".join(f"{wav}|speaker|ZH|test transcript" for wav in sorted(slices.glob("*.wav"))), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "engineering fixture\n", "")

    def test_multi_slice_coverage_and_rerun_isolation(self):
        self.real_audio()
        with patch("services.pipeline_service.run_owned_command", side_effect=self.command_result):
            first = self.run_audio()
            before = dataset_service.get_dataset("test", self.index)
            second = self.run_audio()
        self.assertEqual(first.status, TaskStatus.SUCCEEDED)
        self.assertEqual(second.status, TaskStatus.SUCCEEDED)
        after = dataset_service.get_dataset("test", self.index)
        self.assertNotEqual(before.slice_dir, after.slice_dir)
        self.assertTrue(before.list_path.is_file())
        self.assertEqual(len(dataset_service.load_corrections("test", self.index)), 2)
        self.assertEqual(after.status, "transcribed")
        self.assertFalse(task_service.is_gpu_busy())

    def test_partial_asr_exit_zero_fails_and_preserves_dataset(self):
        self.real_audio()
        def partial(command, **kwargs):
            result = self.command_result(command, **kwargs)
            if command[2].endswith("funasr_asr.py"):
                path = Path(command[6]) / "slices.list"
                path.write_text(path.read_text(encoding="utf-8").splitlines()[0], encoding="utf-8")
            return result
        with patch("services.pipeline_service.run_owned_command", side_effect=partial):
            result = self.run_audio()
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("不一一对应", result.message)
        self.assertEqual(dataset_service.get_dataset("test", self.index), self.dataset)
        self.assertFalse(task_service.is_gpu_busy())

    def test_nonzero_and_timeout_preserve_diagnostics(self):
        self.real_audio()
        for timeout in (False, True):
            with self.subTest(timeout=timeout):
                def failure(command, **kwargs):
                    if timeout:
                        raise subprocess.TimeoutExpired(command, 1)
                    return subprocess.CompletedProcess(command, 7, "", "failure detail")
                with patch("services.pipeline_service.run_owned_command", side_effect=failure) as run:
                    result = self.run_audio()
                self.assertEqual(run.call_count, 1)
                self.assertEqual(result.status, TaskStatus.FAILED)
                self.assertEqual(result.stage, "slicing")
                self.assertIn("超时" if timeout else "7", result.message)
                self.assertFalse(task_service.is_gpu_busy())

    def test_empty_slices_and_invalid_asr_never_publish_dataset(self):
        self.real_audio()
        for case in ("empty_slices", "blank_text", "duplicate", "foreign_slice"):
            with self.subTest(case=case):
                def invalid(command, **kwargs):
                    if case == "empty_slices":
                        return subprocess.CompletedProcess(command, 0, "", "")
                    result = self.command_result(command, **kwargs)
                    if command[2].endswith("funasr_asr.py"):
                        transcript = Path(command[6]) / "slices.list"
                        rows = transcript.read_text(encoding="utf-8").splitlines()
                        if case == "blank_text":
                            rows[0] = rows[0].rsplit("|", 1)[0] + "|"
                        elif case == "duplicate":
                            rows[1] = rows[0]
                        else:
                            rows[0] = str(self.source) + "|speaker|ZH|foreign slice"
                        transcript.write_text("\n".join(rows), encoding="utf-8")
                    return result
                with patch("services.pipeline_service.run_owned_command", side_effect=invalid) as run:
                    result = self.run_audio()
                self.assertEqual(result.status, TaskStatus.FAILED)
                self.assertEqual(run.call_count, 1 if case == "empty_slices" else 2)
                self.assertEqual(dataset_service.get_dataset("test", self.index), self.dataset)
                self.assertFalse(task_service.is_gpu_busy())

    def test_real_audio_crop_and_invalid_bounds(self):
        self.real_audio()
        with wave.open(str(self.source)) as source:
            rate = source.getframerate()
        with patch("services.pipeline_service.run_owned_command", side_effect=self.command_result):
            result = self.run_audio(start=1, end=3)
        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        record = dataset_service.get_dataset("test", self.index)
        with wave.open(str(record.slice_dir.parent / "input.wav")) as cropped:
            self.assertEqual(cropped.getnframes(), 2 * rate)
        for start, end in ((5, 2), (-1, 3), (0, float("nan")), (0, 1e9)):
            with patch("services.pipeline_service.run_owned_command") as run:
                result = self.run_audio(start=start, end=end)
                run.assert_not_called()
                self.assertEqual(result.status, TaskStatus.FAILED)

    def test_gpu_busy_does_not_release_someone_elses_lock(self):
        task_service.try_acquire_gpu()
        try:
            with self.assertRaises(AppError) as ctx:
                self.run_audio()
            self.assertEqual(ctx.exception.code, "GPU_BUSY")
            self.assertTrue(task_service.is_gpu_busy())
        finally:
            task_service.release_gpu()

    def test_invalid_source_is_persisted_without_process(self):
        with patch("services.pipeline_service.run_owned_command") as run:
            result = self.run_audio()
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(task_service.get_task(result.task_id, self.tasks).status, TaskStatus.FAILED)
        run.assert_not_called()

    def test_duplicate_task_id_rejected(self):
        first = self.run_audio(task_id="audio-fixed")
        with self.assertRaises(AppError):
            self.run_audio(task_id="audio-fixed")
        self.assertEqual(task_service.get_task(first.task_id, self.tasks), first)
