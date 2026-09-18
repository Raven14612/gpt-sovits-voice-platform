import json
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from adapters.emotion_classifier import EmotionClassifier, file_hash, map_label
from models.schemas import AppError, DatasetRecord
from services import dataset_service, emotion_service


class EmotionServiceTests(TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory())).resolve()
        self.index = self.root / "data/index/datasets.json"
        for module in (dataset_service, emotion_service):
            self.stack.enter_context(patch.object(module, "PROJECT_ROOT", self.root))
        self.stack.enter_context(patch("services.storage_lock.PROJECT_ROOT", self.root))
        self.stack.enter_context(patch.object(dataset_service, "DATASET_INDEX", self.index))
        self.base = self.root / "data/datasets/d"
        slices = self.base / "slices"
        slices.mkdir(parents=True)
        self.transcript = self.base / "slices.list"
        self.rows = [[f"data/datasets/d/slices/{i}.wav", f"中文文本{i}", "neutral"] for i in range(3)]
        for i in range(3):
            (slices / f"{i}.wav").write_bytes(b"constructed slice, never decoded")
        self.transcript.write_text("\n".join(f"{r[0]}|speaker|zh|{r[1]}" for r in self.rows), encoding="utf-8")
        self.record = DatasetRecord(dataset_id="d", display_name="临时数据", source_path=self.base / "source.wav",
            slice_dir=slices, list_path=self.transcript, status="transcribed", feature_manifest=self.base / "features.json")
        dataset_service.upsert_dataset(self.record, self.index)
        self.classifier = self.stack.enter_context(patch.object(emotion_service, "EmotionClassifier")).return_value
        self.classifier.load.return_value = self.classifier
        self.classifier.config = {"model_id": "emotion-zh-v1"}
        self.classifier.manifest = {"model_version": "test"}
        self.classifier.predict.return_value = [{"happy": .95, "neutral": .05}, {"angry": .99, "neutral": .01}, {"sad": .6, "neutral": .4}]

    def test_generate_accept_and_official_save_are_separate(self):
        emotion_service.suggest_emotions("d")
        latest = dataset_service.get_dataset("d", self.index)
        self.assertEqual(latest.status, self.record.status)
        self.assertEqual(latest.feature_manifest, self.record.feature_manifest)
        self.assertIsNone(latest.emotions_path)
        raw = json.loads(latest.emotion_suggestions_path.read_text(encoding="utf-8"))
        self.assertFalse(Path(raw["annotation_path"]).is_absolute())
        self.assertTrue(raw["items"][1]["requires_review"])
        self.assertEqual(raw["items"][1]["suggested_emotion"], "neutral")
        self.assertIn("[上文]  [当前] 中文文本0 [下文] 中文文本1", self.classifier.predict.call_args.args[0])
        updated = emotion_service.apply_suggestions_to_rows("d", self.rows, high_confidence_only=True)
        self.assertEqual([r[2] for r in updated], ["happy", "neutral", "neutral"])
        self.assertTrue(emotion_service.load_suggestions("d").items[0].accepted)
        # A new interpreter/service instance reads the same disk-only state.
        self.assertEqual(len(emotion_service.load_suggestions("d").items), 3)
        saved = dataset_service.save_corrections("d", updated, index_path=self.index, data_root=self.root / "data/datasets")
        self.assertEqual(set(json.loads(saved.emotions_path.read_text()).values()), {"happy", "neutral"})
        self.assertIsNone(saved.feature_manifest)
        self.assertIsNone(saved.emotion_suggestions_path)

    def test_changed_text_never_applies(self):
        emotion_service.suggest_emotions("d")
        self.transcript.write_text(self.transcript.read_text(encoding="utf-8").replace("文本0", "新文本"), encoding="utf-8")
        self.assertIsNone(emotion_service.load_suggestions("d"))
        with self.assertRaises(AppError) as caught:
            emotion_service.apply_suggestions_to_rows("d", self.rows, high_confidence_only=True)
        self.assertEqual(caught.exception.code, "SUGGESTIONS_STALE")

    def test_concurrent_change_aborts_publication(self):
        predictions = self.classifier.predict.return_value
        def changed(texts):
            self.transcript.write_text(self.transcript.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            return predictions
        self.classifier.predict.side_effect = changed
        with self.assertRaises(AppError) as caught:
            emotion_service.suggest_emotions("d")
        self.assertEqual(caught.exception.code, "DATASET_CHANGED")
        self.assertFalse((self.base / "emotion-suggestions-v1.json").exists())

    def test_model_and_atomic_failures_preserve_old_suggestion(self):
        emotion_service.suggest_emotions("d")
        path = self.base / "emotion-suggestions-v1.json"
        before, index_before = path.read_bytes(), self.index.read_bytes()
        with patch.object(emotion_service.os, "replace", side_effect=PermissionError("blocked")):
            with self.assertRaises(PermissionError):
                emotion_service.suggest_emotions("d")
        self.assertEqual(path.read_bytes(), before)
        self.classifier.predict.side_effect = RuntimeError("model broke")
        with self.assertRaises(RuntimeError):
            emotion_service.suggest_emotions("d")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.index.read_bytes(), index_before)
        self.assertEqual(list(self.base.glob(".emotion-*")), [])

    def test_index_failure_rolls_back_suggestion(self):
        emotion_service.suggest_emotions("d")
        path = self.base / "emotion-suggestions-v1.json"
        before = path.read_bytes()
        with patch.object(dataset_service, "upsert_dataset", side_effect=PermissionError("index blocked")):
            with self.assertRaises(PermissionError):
                emotion_service.suggest_emotions("d")
        self.assertEqual(path.read_bytes(), before)

    def test_manual_edits_and_explicit_neutral_are_protected(self):
        emotion_service.suggest_emotions("d")
        edited = [list(r) for r in self.rows]
        edited[0][1] = "人工修订"
        self.assertEqual(emotion_service.apply_suggestions_to_rows("d", edited, high_confidence_only=True), edited)
        self.assertEqual(emotion_service.apply_suggestions_to_rows("d", self.rows, high_confidence_only=True,
                         protected_paths=[self.rows[0][0]]), self.rows)


class EmotionModelTests(TestCase):
    def test_missing_and_hash_error(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(AppError) as caught:
                EmotionClassifier(root=root).load()
            self.assertEqual(caught.exception.code, "EMOTION_MODEL_MISSING")
            self.assertIn("请联系发布者", caught.exception.message)
            (root / "models/emotion/emotion-zh-v1").mkdir(parents=True)
            with self.assertRaises(AppError) as caught:
                EmotionClassifier(root=root).load()
            self.assertEqual(caught.exception.code, "EMOTION_MODEL_INVALID")

    def test_mapping_never_accepts_unsupported_emotion(self):
        for label in ("angry", "fear", "surprise", "disgust", "concern", "question"):
            self.assertEqual(map_label(label), ("neutral", True))
        for label, value in (("joy", "happy"), ("sadness", "sad"), ("neutral", "neutral")):
            self.assertEqual(map_label(label), (value, False))
