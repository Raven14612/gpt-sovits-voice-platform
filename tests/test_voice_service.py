from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional, Tuple
from unittest import TestCase
from unittest.mock import patch

from models.schemas import AppError, DatasetRecord, TaskStatus
from services.task_service import get_task, list_tasks, try_acquire_gpu, release_gpu
from services.voice_service import (
    _archive_weight, _checkpoint_snapshot, _checkpoint_state, _require_checkpoint_change,
    _resolve_checkpoint,
    _validate_voice_id, get_voice_profile, train_voice,
)


def _real_checkpoint_paths() -> Tuple[Optional[Path], Optional[Path]]:
    gpt = os.environ.get("GPT_SOVITS_REAL_GPT_WEIGHT")
    sovits = os.environ.get("GPT_SOVITS_REAL_SOVITS_WEIGHT")
    return (Path(gpt) if gpt else None, Path(sovits) if sovits else None)


class VoiceServiceTests(TestCase):
    def setUp(self) -> None:
        self.root = (Path(__file__).resolve().parent / "_tmp_voice" / self._testMethodName).resolve()
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
                    "import shutil",
                    "import sys",
                    "import time",
                    "",
                    "mode = sys.argv[1]",
                    "source = Path(sys.argv[2])",
                    "target = Path(sys.argv[3])",
                    "if mode == 'copy':",
                    "    target.parent.mkdir(parents=True, exist_ok=True)",
                    "    shutil.copy2(source, target)",
                    "elif mode == 'empty':",
                    "    target.parent.mkdir(parents=True, exist_ok=True)",
                    "    target.touch()",
                    "elif mode == 'sleep':",
                    "    time.sleep(2)",
                    "elif mode == 'skip':",
                    "    pass",
                    "elif mode == 'fail':",
                    "    raise SystemExit(7)",
                    "else:",
                    "    raise SystemExit(9)",
                ]
            ),
            encoding="utf-8",
        )
        return script

    def _dataset(self, dataset_id: str = "dataset-1") -> DatasetRecord:
        return DatasetRecord(dataset_id=dataset_id, display_name="test", source_path=self.root / "input.wav")

    def _source_file(self, name: str) -> Path:
        path = self.root / name
        path.write_text("stage-input", encoding="utf-8")
        return path

    def _plan(self, *, voice_id: str, gpt_mode: str, sovits_mode: str, gpt_output: Path, sovits_output: Path,
              task_index: Path, voice_index: Path, archive_root: Path, log_dir: Path, gpt_timeout: int = 10,
              sovits_timeout: int = 10) -> dict:
        real_gpt_weight, real_sovits_weight = _real_checkpoint_paths()
        gpt_source = real_gpt_weight or self._source_file(f"{voice_id}-gpt-source.bin")
        sovits_source = real_sovits_weight or self._source_file(f"{voice_id}-sovits-source.bin")
        return {
            "task_id": f"task-{voice_id}",
            "display_name": voice_id,
            "feature_name": voice_id,
            "engine_profile": "local-gpt-sovits",
            "task_index": task_index,
            "voice_index": voice_index,
            "archive_root": archive_root,
            "log_dir": log_dir,
            "gpt_command": [sys.executable, str(self.script), gpt_mode, str(gpt_source), str(gpt_output)],
            "gpt_cwd": self.root,
            "gpt_outputs": [gpt_output],
            "gpt_weight_path": gpt_output,
            "gpt_timeout": gpt_timeout,
            "sovits_command": [sys.executable, str(self.script), sovits_mode, str(sovits_source), str(sovits_output)],
            "sovits_cwd": self.root,
            "sovits_outputs": [sovits_output],
            "sovits_weight_path": sovits_output,
            "sovits_timeout": sovits_timeout,
            "allowed_roots": [self.root, gpt_output.parent, sovits_output.parent, archive_root],
        }

    def test_missing_gpt_command_returns_not_implemented(self) -> None:
        with TemporaryDirectory() as directory:
            index = Path(directory) / "tasks.json"
            voice_index = Path(directory) / "voices.json"
            with self.assertRaises(AppError) as ctx:
                train_voice(self._dataset(), "voice-1", {"task_index": index, "voice_index": voice_index})
            self.assertEqual(ctx.exception.code, "NOT_IMPLEMENTED")

    def test_gpt_failure_marks_task_failed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task_index = root / "tasks.json"
            voice_index = root / "voices.json"
            archive_root = root / "archive"
            params = self._plan(
                voice_id="voice-gpt-fail",
                gpt_mode="fail",
                sovits_mode="copy",
                gpt_output=root / "gpt.ckpt",
                sovits_output=root / "sovits.pth",
                task_index=task_index,
                voice_index=voice_index,
                archive_root=archive_root,
                log_dir=root / "logs",
            )
            task = train_voice(self._dataset(), "voice-gpt-fail", params)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertEqual(task.stage, "train_gpt")
            self.assertIsNone(get_voice_profile("voice-gpt-fail", voice_index))

    def test_sovits_failure_marks_task_failed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task_index = root / "tasks.json"
            voice_index = root / "voices.json"
            archive_root = root / "archive"
            params = self._plan(
                voice_id="voice-sovits-fail",
                gpt_mode="copy",
                sovits_mode="fail",
                gpt_output=root / "gpt.ckpt",
                sovits_output=root / "sovits.pth",
                task_index=task_index,
                voice_index=voice_index,
                archive_root=archive_root,
                log_dir=root / "logs",
            )
            task = train_voice(self._dataset(), "voice-sovits-fail", params)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertEqual(task.stage, "train_sovits")
            self.assertIsNone(get_voice_profile("voice-sovits-fail", voice_index))

    def test_timeout_marks_task_failed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task_index = root / "tasks.json"
            voice_index = root / "voices.json"
            archive_root = root / "archive"
            params = self._plan(
                voice_id="voice-timeout",
                gpt_mode="sleep",
                sovits_mode="copy",
                gpt_output=root / "gpt.ckpt",
                sovits_output=root / "sovits.pth",
                task_index=task_index,
                voice_index=voice_index,
                archive_root=archive_root,
                log_dir=root / "logs",
                gpt_timeout=1,
            )
            task = train_voice(self._dataset(), "voice-timeout", params)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertEqual(task.stage, "train_gpt")
            self.assertIsNone(get_voice_profile("voice-timeout", voice_index))

    def test_missing_weight_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task_index = root / "tasks.json"
            voice_index = root / "voices.json"
            archive_root = root / "archive"
            params = self._plan(
                voice_id="voice-missing",
                gpt_mode="copy",
                sovits_mode="skip",
                gpt_output=root / "gpt.ckpt",
                sovits_output=root / "missing.pth",
                task_index=task_index,
                voice_index=voice_index,
                archive_root=archive_root,
                log_dir=root / "logs",
            )
            task = train_voice(self._dataset(), "voice-missing", params)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertEqual(task.stage, "train_sovits")
            self.assertIsNone(get_voice_profile("voice-missing", voice_index))

    def test_empty_weight_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task_index = root / "tasks.json"
            voice_index = root / "voices.json"
            archive_root = root / "archive"
            params = self._plan(
                voice_id="voice-empty",
                gpt_mode="copy",
                sovits_mode="empty",
                gpt_output=root / "gpt.ckpt",
                sovits_output=root / "empty.pth",
                task_index=task_index,
                voice_index=voice_index,
                archive_root=archive_root,
                log_dir=root / "logs",
            )
            task = train_voice(self._dataset(), "voice-empty", params)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertEqual(task.stage, "packaging")
            self.assertIsNone(get_voice_profile("voice-empty", voice_index))

    def test_invalid_extension_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task_index = root / "tasks.json"
            voice_index = root / "voices.json"
            archive_root = root / "archive"
            params = self._plan(
                voice_id="voice-invalid",
                gpt_mode="copy",
                sovits_mode="copy",
                gpt_output=root / "gpt.txt",
                sovits_output=root / "invalid.txt",
                task_index=task_index,
                voice_index=voice_index,
                archive_root=archive_root,
                log_dir=root / "logs",
            )
            task = train_voice(self._dataset(), "voice-invalid", params)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertEqual(task.stage, "packaging")
            self.assertIsNone(get_voice_profile("voice-invalid", voice_index))

    def test_archive_failure_fails_before_profile_write(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task_index = root / "tasks.json"
            voice_index = root / "voices.json"
            archive_root = root / "archive.lock"
            archive_root.write_text("blocked", encoding="utf-8")
            params = self._plan(
                voice_id="voice-archive-fail",
                gpt_mode="copy",
                sovits_mode="copy",
                gpt_output=root / "gpt.ckpt",
                sovits_output=root / "sovits.pth",
                task_index=task_index,
                voice_index=voice_index,
                archive_root=archive_root,
                log_dir=root / "logs",
            )
            task = train_voice(self._dataset(), "voice-archive-fail", params)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertEqual(task.stage, "packaging")
            self.assertIsNone(get_voice_profile("voice-archive-fail", voice_index))

    def test_success_path_writes_voice_profile_last(self) -> None:
        real_gpt_weight, real_sovits_weight = _real_checkpoint_paths()
        if real_gpt_weight is None or real_sovits_weight is None:
            self.skipTest("real checkpoint fixtures are unavailable")
        if not real_gpt_weight.is_file() or not real_sovits_weight.is_file():
            self.skipTest("real checkpoint fixtures are unavailable")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task_index = root / "tasks.json"
            voice_index = root / "voices.json"
            archive_root = root / "archive"
            gpt_output = root / "gpt.ckpt"
            sovits_output = root / "sovits.pth"
            params = self._plan(
                voice_id="voice-success",
                gpt_mode="copy",
                sovits_mode="copy",
                gpt_output=gpt_output,
                sovits_output=sovits_output,
                task_index=task_index,
                voice_index=voice_index,
                archive_root=archive_root,
                log_dir=root / "logs",
            )
            task = train_voice(self._dataset(), "voice-success", params)
            self.assertEqual(task.status, TaskStatus.SUCCEEDED)
            profile = get_voice_profile("voice-success", voice_index)
            self.assertIsNotNone(profile)
            self.assertTrue(profile.gpt_weight.is_file())
            self.assertTrue(profile.sovits_weight.is_file())
            self.assertIn(archive_root.resolve(), profile.gpt_weight.resolve().parents)
            self.assertIn(archive_root.resolve(), profile.sovits_weight.resolve().parents)

    def test_gpu_busy_rejects_second_training_task(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task_index = root / "tasks.json"
            voice_index = root / "voices.json"
            archive_root = root / "archive"
            params = self._plan(
                voice_id="voice-busy",
                gpt_mode="sleep",
                sovits_mode="copy",
                gpt_output=root / "gpt.ckpt",
                sovits_output=root / "sovits.pth",
                task_index=task_index,
                voice_index=voice_index,
                archive_root=archive_root,
                log_dir=root / "logs",
            )
            try:
                try_acquire_gpu()
                with self.assertRaises(AppError) as ctx:
                    train_voice(self._dataset(), "voice-busy", params)
                self.assertEqual(ctx.exception.code, "GPU_BUSY")
            finally:
                release_gpu()

    def test_invalid_voice_ids_rejected_before_side_effects(self):
        invalid = ("", ".", "..", "../outside", "..\\outside", "/absolute", "C:\\outside",
                   "C:relative", "voice/child", "voice\\child", "voice:stream", "CON", "nul.txt",
                   "LPT1", "COM1.ckpt", "voice.", "voice ", "bad\x00id", "bad?name")
        with patch("services.voice_service.PipelineRunner") as runner:
            for voice_id in invalid:
                with self.subTest(voice_id=voice_id), self.assertRaises(AppError) as ctx:
                    train_voice(self._dataset(), voice_id, {})
                self.assertEqual(ctx.exception.code, "INVALID_VOICE_ID")
            runner.assert_not_called()
        for voice_id in ("citlali", "voice-success", "音色一"):
            _validate_voice_id(voice_id)

    def test_archive_rejects_directory_junction_escape(self):
        archive = self.root / "archive"
        outside = self.root / "outside"
        archive.mkdir()
        outside.mkdir()
        link = archive / "voice"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
        else:
            link.symlink_to(outside, target_is_directory=True)
        source = self._source_file("source.txt")
        try:
            with self.assertRaises(AppError) as ctx:
                _archive_weight(source, archive, "voice")
            self.assertEqual(ctx.exception.code, "OUTPUT_INVALID")
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            if os.name == "nt":
                link.rmdir()
            else:
                link.unlink()

    def test_archive_rejects_existing_target_link_escape(self):
        archive = self.root / "archive"
        source = self._source_file("source.txt")
        outside = self._source_file("outside.txt")
        target = archive / "voice" / source.name
        target.parent.mkdir(parents=True)
        original_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == target:
                return outside
            return original_resolve(path, *args, **kwargs)

        # Windows file symlinks can require admin rights; model only the resolved link.
        with patch.object(Path, "resolve", resolve):
            with self.assertRaises(AppError) as ctx:
                _archive_weight(source, archive, "voice")
        self.assertEqual(ctx.exception.code, "OUTPUT_INVALID")
        self.assertEqual(outside.read_text(encoding="utf-8"), "stage-input")

    def test_snapshot_detects_content_change_with_preserved_metadata(self):
        source = self._source_file("snapshot.bin")
        before = _checkpoint_snapshot(source, [self.root])
        original = source.stat()
        source.write_text("stage-other", encoding="utf-8")
        os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(source.stat().st_size, original.st_size)
        _require_checkpoint_change(source, [self.root], before)

    def test_snapshot_rejects_timestamp_only_change(self):
        source = self._source_file("snapshot.bin")
        before = _checkpoint_snapshot(source, [self.root])
        original = source.stat()
        os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns + 10_000_000_000))
        with self.assertRaises(AppError) as ctx:
            _require_checkpoint_change(source, [self.root], before)
        self.assertEqual(ctx.exception.code, "OUTPUT_STALE")

    def test_checkpoint_glob_selects_new_matching_weight(self):
        pattern = str(self.root / "voice_e8_s*.pth")
        before = _checkpoint_state(None, pattern, [self.root])
        output = self.root / "voice_e8_s176.pth"
        output.write_bytes(b"\x05\x00binary-checkpoint")
        selected = _resolve_checkpoint(None, pattern, [self.root], before)
        self.assertEqual(selected, output)

    def test_existing_real_weights_cannot_report_new_training_success(self):
        gpt, sovits = _real_checkpoint_paths()
        if gpt is None or sovits is None or not gpt.is_file() or not sovits.is_file():
            self.skipTest("real checkpoint fixtures are unavailable")
        for stale in ("gpt", "sovits", "both"):
            with self.subTest(stale=stale), TemporaryDirectory() as directory:
                root = Path(directory)
                params = self._plan(
                    voice_id="stale", gpt_mode="skip" if stale in ("gpt", "both") else "copy",
                    sovits_mode="skip" if stale in ("sovits", "both") else "copy",
                    gpt_output=root / "gpt.ckpt", sovits_output=root / "sovits.pth",
                    task_index=root / "tasks.json", voice_index=root / "voices.json",
                    archive_root=root / "archive", log_dir=root / "logs",
                )
                if stale in ("gpt", "both"):
                    shutil.copy2(gpt, params["gpt_weight_path"])
                if stale in ("sovits", "both"):
                    shutil.copy2(sovits, params["sovits_weight_path"])
                result = train_voice(self._dataset(), "stale", params)
                self.assertEqual(result.status, TaskStatus.FAILED)
                self.assertEqual(result.stage, "packaging")
                self.assertIn("本次训练未生成新的权重内容", result.message)
                self.assertEqual(get_task(result.task_id, params["task_index"]).status, TaskStatus.FAILED)
                self.assertIsNone(get_voice_profile("stale", params["voice_index"]))
                self.assertFalse(params["archive_root"].exists())
                try_acquire_gpu()
                release_gpu()
