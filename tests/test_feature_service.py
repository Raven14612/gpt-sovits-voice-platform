import json
import os
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from models.schemas import AppError, DatasetRecord, TaskStatus
from services import dataset_service, feature_service, task_service


class FeatureServiceTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.directory = self.root / "data/datasets/d"
        self.slices = self.directory / "slices"
        self.slices.mkdir(parents=True)
        self.index, self.tasks = self.root / "datasets.json", self.root / "tasks.json"
        self.config = self.root / "engine.json"
        self.config.write_text(json.dumps({"engine_root": str(self.root), "python_path": sys.executable}))
        self.transcript = self.directory / "reviewed.list"
        self.record = DatasetRecord(dataset_id="d", display_name="test", source_path=self.directory / "source.wav",
                                    slice_dir=self.slices, list_path=self.transcript, status="reviewed")
        dataset_service.upsert_dataset(self.record, self.index)
        for patcher in (patch.object(feature_service, "PROJECT_ROOT", self.root),
                        patch.object(feature_service.GPTSoVITSAdapter, "feature_environment", return_value={}),
                        patch.object(feature_service.GPTSoVITSAdapter, "feature_command", side_effect=lambda stage: [stage])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def prepare(self):
        source = os.environ.get("GPT_SOVITS_REAL_AUDIO")
        if not source or not Path(source).is_file():
            self.skipTest("real audio fixture unavailable")
        for path in (self.record.source_path, self.slices / "one.wav", self.slices / "two.wav"):
            shutil.copy2(source, path)
        self.transcript.write_text("\n".join(f"{p}|speaker|ZH|测试文本" for p in sorted(self.slices.glob("*.wav"))), encoding="utf-8")

    def run_features(self):
        return feature_service.extract_features("d", config_path=self.config, dataset_index=self.index, task_index=self.tasks)

    def stage(self, task, stage, command, **kwargs):
        self.assertTrue(task_service.is_gpu_busy())
        self.assertFalse(kwargs["gpu"])
        for path in kwargs["outputs"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".wav":
                shutil.copy2(self.record.source_path, path)
            elif path.name == "2-name2text-0.txt":
                path.write_text("one.wav\ta b\t[1, 1]\t测试\ntwo.wav\tc d\t[1, 1]\t文本\n", encoding="utf-8")
            elif path.suffix == ".tsv":
                path.write_text("one.wav\t1 2 3\ntwo.wav\t4 5 6\n", encoding="utf-8")
            else:
                # Engineering-only feature placeholders, never model checkpoint evidence.
                path.write_text("engineering feature fixture", encoding="utf-8")
        return task_service.transition(task, TaskStatus.RUNNING, stage=stage)

    def test_complete_serial_outputs_and_manifest(self):
        self.prepare()
        with patch.object(feature_service.PipelineRunner, "run_stage", side_effect=self.stage) as run:
            result = self.run_features()
        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertEqual([call.args[1] for call in run.call_args_list],
                         ["feature_text", "feature_hubert", "feature_sv", "feature_semantic"])
        record = dataset_service.get_dataset("d", self.index)
        self.assertEqual(record.status, "reviewed")
        manifest = json.loads(record.feature_manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["slices"], 2)
        self.assertFalse(manifest["training_started"])
        self.assertTrue((record.feature_manifest.parent / "6-name2semantic.tsv").read_text().startswith("item_name\tsemantic_audio"))
        self.assertFalse(task_service.is_gpu_busy())

    def test_partial_success_exit_does_not_attach_features(self):
        self.prepare()
        def partial(task, stage, command, **kwargs):
            result = self.stage(task, stage, command, **kwargs)
            if stage == "feature_text":
                kwargs["outputs"][0].write_text("one.wav\ta\t[1]\t测试\n", encoding="utf-8")
            return result
        with patch.object(feature_service.PipelineRunner, "run_stage", side_effect=partial) as run:
            result = self.run_features()
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(run.call_count, 1)
        self.assertIsNone(dataset_service.get_dataset("d", self.index).feature_manifest)

    def test_changed_dataset_does_not_publish_stale_features(self):
        self.prepare()
        def changed(task, stage, command, **kwargs):
            result = self.stage(task, stage, command, **kwargs)
            if stage == "feature_semantic":
                dataset_service.upsert_dataset(self.record.model_copy(update={"display_name": "changed"}), self.index)
            return result
        with patch.object(feature_service.PipelineRunner, "run_stage", side_effect=changed):
            result = self.run_features()
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("DATASET_CHANGED", result.message)
        self.assertEqual(dataset_service.get_dataset("d", self.index).display_name, "changed")
        self.assertIsNone(dataset_service.get_dataset("d", self.index).feature_manifest)

    def test_unreviewed_and_gpu_busy_do_not_execute(self):
        dataset_service.upsert_dataset(self.record.model_copy(update={"status": "transcribed"}), self.index)
        with patch.object(feature_service.PipelineRunner, "run_stage") as run:
            result = self.run_features()
            run.assert_not_called()
        self.assertIn("DATASET_NOT_READY", result.message)
        task_service.try_acquire_gpu()
        try:
            with self.assertRaises(AppError) as context:
                self.run_features()
            self.assertEqual(context.exception.code, "GPU_BUSY")
            self.assertTrue(task_service.is_gpu_busy())
        finally:
            task_service.release_gpu()

    def test_train_features_uses_explicit_training_task_kind(self):
        self.prepare()
        with patch.object(feature_service.PipelineRunner, "run_stage", side_effect=self.stage):
            result = feature_service.train_features("d", config_path=self.config,
                dataset_index=self.index, task_index=self.tasks)
        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.kind, "train_features")
