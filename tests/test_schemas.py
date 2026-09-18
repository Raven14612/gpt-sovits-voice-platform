from pathlib import Path
from unittest import TestCase

from models.schemas import DatasetRecord, EmotionSuggestionItem, EngineConfig, TaskRecord, TaskStatus, VoiceProfile


class SchemaTests(TestCase):
    def test_v1_defaults_and_suggestion_validation(self):
        dataset = DatasetRecord(dataset_id="d", display_name="V1", source_path=Path("source.wav"))
        voice = VoiceProfile(voice_id="v", display_name="V1", feature_name="f", dataset_id="d", engine_profile="v2Pro")
        self.assertIsNone(dataset.emotion_suggestions_path)
        self.assertEqual(voice.origin_type, "local_training")
        self.assertIsNone(voice.package_hash)
        for confidence in (-.1, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                EmotionSuggestionItem(audio_path=Path("a.wav"), text_sha256="a"*64, suggested_emotion="neutral",
                                      raw_label="angry", confidence=confidence, requires_review=True)

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
