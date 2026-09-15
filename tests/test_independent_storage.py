import json
import os
import wave
import asyncio
import subprocess
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from types import SimpleNamespace

from models.schemas import AppError, GenerationRecord
from services import asset_service as assets, dataset_service as datasets, history_service as history
from services import training_preparation_service as preparation
from services import voice_service
from models.schemas import DatasetRecord, VoiceProfile
from ui import result_page, layout


def wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 160)


class IndependentStorageTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module in (datasets, history):
            self.stack.enter_context(patch.object(module, "PROJECT_ROOT", self.root))
        self.index = self.root / "data/index/voices.json"
        self.di = self.root / "data/index/datasets.json"
        self.stack.enter_context(patch.object(datasets, "DATASET_INDEX", self.di))
        self.stack.enter_context(patch.object(history, "HISTORY_INDEX", self.root / "data/index/history.json"))
        self.stack.enter_context(patch.object(history, "OUTPUT_ROOT", self.root / "data/outputs"))
        self.stack.enter_context(patch("services.task_service.try_acquire_gpu"))
        self.stack.enter_context(patch("services.task_service.release_gpu"))
        self.base = self.root / "data/datasets/d"
        wav(self.base / "source.wav")
        wav(self.base / "processing/task/slices/a.wav")
        self.slice = self.base / "processing/task/slices/a.wav"
        self.revision = self.root / "data/datasets/old-revision"
        self.revision.mkdir()
        (self.revision / "corrected.list").write_text(f"{self.slice}|能天使|zh|你好，博士。\n", encoding="utf-8")
        assets.atomic_json(self.revision / "emotions.json", {str(self.slice): "neutral"})
        self.dataset = {"dataset_id": "d", "display_name": "能天使原音频", "source_path": "data/datasets/d/source.wav",
                        "slice_dir": "data/datasets/d/processing/task/slices", "list_path": "data/datasets/old-revision/corrected.list",
                        "emotions_path": "data/datasets/old-revision/emotions.json", "status": "reviewed"}
        assets.atomic_json(self.di, [self.dataset])
        self.archive = self.root / "data/voices/v"
        self.archive.mkdir(parents=True)
        (self.archive / "g.ckpt").write_bytes(b"GPT")
        (self.archive / "s.pth").write_bytes(b"SoVITS")
        self.voice = {"voice_id": "v", "display_name": "能天使", "feature_name": "v", "dataset_id": "d",
                      "engine_profile": "local", "status": "verified", "gpt_weight": "data/voices/v/g.ckpt",
                      "sovits_weight": "data/voices/v/s.pth", "references": [{"audio_path": str(self.slice),
                      "emotion": "neutral", "prompt_text": "你好，博士。", "language": "zh"}]}
        assets.atomic_json(self.index, [self.voice])
        self.training = self.root / "data/training/run"
        assets.atomic_json(self.training / "plan.json", {"dataset_id": "d", "voice_id": "v"})
        (self.training / "intermediate.ckpt").write_bytes(b"checkpoint")
        self.output = self.root / "data/outputs/result.wav"
        wav(self.output)
        history.add_history(GenerationRecord(result_id="result", voice_id="v", text="你好，博士。", output_path=self.output,
            status="succeeded", source_snapshot={"voice_name": "能天使", "dataset_name": "能天使原音频"}))

    def test_delete_all_materials_keeps_independent_crud_and_external_original(self):
        external = self.root / "用户原始文件.wav"
        wav(external)
        before = history.file_hash(self.output)
        plan = voice_service.prepare_voice_purge("v", self.index)
        self.assertGreater(plan["files"], 6)
        with patch.object(voice_service, "try_acquire_gpu"), patch.object(voice_service, "release_gpu"):
            voice_service.purge_voice("v", plan["fingerprint"], self.index)
        for path in (self.base, self.revision, self.archive, self.training):
            self.assertFalse(path.exists(), path)
        self.assertTrue(external.exists())
        self.assertEqual(assets.read_json(self.index), [])
        self.assertEqual(assets.read_json(self.di), [])
        self.assertEqual(history.file_hash(self.output), before)
        history.edit_result("result", "欢迎博士", "独立成品备注")
        self.assertIn("能天使", result_page.result_choices("独立成品")[0][0])
        self.assertTrue(Path(history.download_result("result")).is_file())
        self.assertEqual(history.get_result_output("result"), str(self.output))
        with patch.object(layout.voice_service, "get_voice", return_value=None), patch.object(layout, "voice_choices", return_value=[]):
            reused = layout.reuse_to_tts("result")
        self.assertEqual(reused[2], "你好，博士。")
        self.assertIsNone(reused[0])
        self.assertTrue(history.delete_history("result"))
        self.assertFalse(self.output.exists())

    def test_changed_plan_is_rejected_without_deleting_anything(self):
        plan = assets.deletion_plan("v", self.index, self.root)
        (self.archive / "g.ckpt").write_bytes(b"updated GPT")
        with self.assertRaises(AppError):
            assets.execute_delete(plan, self.index, self.root)
        self.assertTrue(self.base.exists())
        self.assertEqual(len(assets.read_json(self.index)), 1)

    def test_staging_failure_rolls_back_files_and_indices(self):
        plan = assets.deletion_plan("v", self.index, self.root)
        replace = os.replace
        moves = 0
        def fail_second(source, target):
            nonlocal moves
            if Path(target).parent.name == "files":
                moves += 1
                if moves == 2:
                    raise PermissionError("file occupied")
            return replace(source, target)
        with patch.object(assets.os, "replace", side_effect=fail_second):
            with self.assertRaises(PermissionError):
                assets.execute_delete(plan, self.index, self.root)
        self.assertTrue(self.base.exists())
        self.assertTrue(self.revision.exists())
        self.assertEqual(len(assets.read_json(self.index)), 1)
        assets.ensure_ready(self.root)

    def test_committed_failure_recovers_and_does_not_report_done_early(self):
        plan = assets.deletion_plan("v", self.index, self.root)
        with patch.object(assets.shutil, "rmtree", side_effect=PermissionError("occupied")):
            with self.assertRaises(AppError) as error:
                assets.execute_delete(plan, self.index, self.root)
        self.assertEqual(error.exception.code, "DELETE_PENDING")
        with self.assertRaises(AppError):
            assets.ensure_ready(self.root)
        self.assertTrue(assets.recover_deletions(self.root))
        assets.ensure_ready(self.root)
        self.assertTrue(self.output.exists())
        self.assertEqual(list((self.root / "data/deletions").glob("*/files/*")), [])

    def test_shared_dataset_is_split_before_one_group_is_deleted(self):
        other = dict(self.voice, voice_id="other", gpt_weight=None, sovits_weight=None,
                     references=[dict(self.voice["references"][0])])
        assets.atomic_json(self.index, [self.voice, other])
        with self.assertRaises(AppError):
            assets.deletion_plan("v", self.index, self.root)
        assets.migrate_ownership(self.root)
        voices = assets.read_json(self.index)
        self.assertNotEqual(voices[0]["dataset_id"], voices[1]["dataset_id"])
        second_ref = self.root / voices[1]["references"][0]["audio_path"]
        assets.execute_delete(assets.deletion_plan("v", self.index, self.root), self.index, self.root)
        self.assertTrue(second_ref.exists())
        self.assertEqual(len(assets.read_json(self.index)), 1)

    def test_delete_rejects_external_weight_and_directory_link(self):
        self.voice["gpt_weight"] = str(self.output)
        assets.atomic_json(self.index, [self.voice])
        with self.assertRaises(AppError):
            assets.deletion_plan("v", self.index, self.root)
        self.assertTrue(self.output.exists())

    def test_chinese_names_and_all_new_annotation_versions_are_owned(self):
        record = datasets.get_dataset("d", self.di)
        rows = datasets.load_corrections("d", self.di)
        for name in ("能天使·第一版", "能天使·最终标注"):
            datasets.save_corrections("d", rows, index_path=self.di, data_root=self.root / "data/datasets", annotation_name=name)
        exported = datasets.export_transcript("d")
        self.assertIn("能天使·最终标注", exported)
        datasets.rename_dataset("d", "能天使·中文数据集")
        self.assertEqual(datasets.get_dataset("d", self.di).display_name, "能天使·中文数据集")
        self.assertEqual(len(list((record.source_path.parent / "annotations").iterdir())), 2)
        assets.execute_delete(assets.deletion_plan("v", self.index, self.root), self.index, self.root)
        self.assertFalse(Path(exported).exists())

    def test_missing_result_edit_cannot_resurrect_deleted_audio(self):
        history.delete_history("result")
        with self.assertRaises(AppError):
            history.edit_result("result", "新名称")
        self.assertEqual(history.list_history(), [])

    def test_legacy_backfill_freezes_names_without_claiming_historical_hashes(self):
        records = history._read()
        records[0].pop("source_snapshot")
        history._write(records)
        with patch("services.voice_service.get_voice", return_value=VoiceProfile.model_validate(self.voice)), \
                patch.object(datasets, "get_dataset", return_value=DatasetRecord.model_validate(self.dataset)):
            self.assertEqual(history.backfill_snapshots(), 1)
        with patch("services.voice_service.get_voice", side_effect=AssertionError("must not consult deleted voice")):
            self.assertEqual(history.backfill_snapshots(), 0)
            self.assertIn("能天使", result_page.result_choices()[0][0])
        self.assertEqual(history._read()[0]["source_snapshot"]["provenance"], "legacy_backfill")
        self.assertNotIn("sha256", history._read()[0]["source_snapshot"]["gpt_weight"])

    def prepare_feature_fixture(self):
        feature = self.base / "features/task"
        outputs = []
        for name in ("2-name2text.txt", "6-name2semantic.tsv", "3-bert/a.wav.pt", "4-cnhubert/a.wav.pt",
                     "5-wav32k/a.wav", "7-sv_cn/a.wav.pt"):
            path = feature / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"feature-data")
            outputs.append({"path": path.relative_to(self.root).as_posix(), "bytes": path.stat().st_size})
        transcript = self.revision / "corrected.list"
        (feature / "input.list").write_bytes(transcript.read_bytes())
        assets.atomic_json(feature / "manifest.json", {"dataset_id": "d", "version": "v2Pro", "slices": 1,
            "inputs_sha256": {str(p): history.file_hash(p) for p in (transcript, self.slice)}, "outputs": outputs})
        self.dataset["feature_manifest"] = (feature / "manifest.json").relative_to(self.root).as_posix()
        assets.atomic_json(self.di, [self.dataset])
        return feature

    def test_second_training_prepares_valid_independent_inputs_without_gpu(self):
        self.prepare_feature_fixture()
        engine = self.root / "engine"
        assets.atomic_json(engine / "GPT_SoVITS/configs/s2v2Pro.json", {"train": {}, "model": {}, "data": {}})
        config = engine / "GPT_SoVITS/configs/s1longer-v2.yaml"
        config.write_text("train: {}\n", encoding="utf-8")
        for name in ("GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth", "GPT_SoVITS/pretrained_models/v2Pro/s2Dv2Pro.pth",
                     "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
                     "GPT_SoVITS/s1_train.py", "GPT_SoVITS/s2_train.py", "python.exe"):
            path = engine / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        with patch.object(preparation, "PROJECT_ROOT", self.root), patch.object(preparation, "_load_config",
                return_value=SimpleNamespace(engine_root=engine, python_path=engine / "python.exe")):
            plan = preparation.prepare_training("d", "second", dataset_index=self.di)
        data = assets.read_json(plan)
        self.assertNotEqual(data["dataset_id"], "d")
        clone = datasets.get_dataset(data["dataset_id"], self.di)
        manifest = assets.read_json(clone.feature_manifest)
        for value, digest in manifest["inputs_sha256"].items():
            self.assertEqual(history.file_hash(self.root / value), digest)
            self.assertNotIn("/datasets/d/", value)
        refs = preparation._training_references(clone)
        self.assertTrue(refs[0].audio_path.is_relative_to(clone.source_path.parent))
        self.assertTrue((plan.parent / "experiment/3-bert/a.wav.pt").exists())
        self.assertEqual(list((plan.parent / "GPT_weights").iterdir()), [])

    def test_clone_never_revalidates_features_from_modified_audio(self):
        self.prepare_feature_fixture()
        self.slice.write_bytes(b"modified-after-feature-extraction")
        before = assets.read_json(self.di)
        with self.assertRaises(AppError) as error:
            assets.clone_dataset("d", root=self.root)
        self.assertEqual(error.exception.code, "DATASET_CHANGED")
        self.assertEqual(assets.read_json(self.di), before)

    def test_known_upload_cache_deleted_but_external_original_preserved(self):
        cache = self.root / "data/tmp/gradio/upload/能天使.wav"
        wav(cache)
        assets.atomic_json(self.base / "ownership.json", {"dataset_id": "d", "upload_cache_files": [cache.relative_to(self.root).as_posix()]})
        assets.execute_delete(assets.deletion_plan("v", self.index, self.root), self.index, self.root)
        self.assertFalse(cache.exists())
        self.assertTrue(self.output.exists())

    def test_windows_junction_is_rejected_without_touching_target(self):
        link = self.base / "linked-output"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(self.output.parent)], capture_output=True)
        if result.returncode:
            self.skipTest("junction creation unavailable")
        try:
            with self.assertRaises(AppError) as error:
                assets.deletion_plan("v", self.index, self.root)
            self.assertEqual(error.exception.code, "DELETE_PATH_INVALID")
            self.assertTrue(self.output.exists())
        finally:
            link.rmdir()

    def test_gradio_workbench_selection_edit_search_and_download(self):
        from app import build_app
        from gradio.state_holder import SessionState
        with patch("ui.layout._status_markdown", return_value="测试环境"):
            app = build_app()
        session = SessionState(app)
        def callback(fn):
            return next(f for f in app.fns.values() if f.fn is fn)
        async def exercise():
            search = await app.process_api(callback(result_page.search_results), ["  能天使  ", None], state=session)
            self.assertEqual(search["data"][0]["value"], "result")
            self.assertIn("找到 1 条", search["data"][1])
            selected = await app.process_api(callback(result_page.select_result), [search["data"][0]["value"]], state=session)
            self.assertEqual(Path(selected["data"][1]["path"]).read_bytes(), self.output.read_bytes())
            missing = await app.process_api(callback(result_page.search_results), ["不存在的角色", "result"], state=session)
            self.assertIsNone(missing["data"][0]["value"])
            self.assertEqual(missing["data"][0]["choices"], [])
            self.assertIn("未找到", missing["data"][1])
            cleared = await app.process_api(callback(result_page.search_results), ["", None], state=session)
            self.assertEqual(cleared["data"][0]["value"], "result")
            self.assertEqual(cleared["data"][1], "")
            details = await app.process_api(callback(result_page.result_details), ["result"], state=session)
            self.assertIn("能天使", details["data"][2])
            saved = await app.process_api(callback(result_page.save_result_details), ["result", "中文欢迎语", "工作台备注", ""], state=session)
            self.assertIn("已保存", saved["data"][1])
            self.assertIn("中文欢迎语", result_page.result_choices("工作台备注")[0][0])
            downloaded = await app.process_api(callback(result_page.prepare_download), ["result"], state=session)
            self.assertIn("中文欢迎语", downloaded["data"][0]["orig_name"])
        asyncio.run(exercise())
