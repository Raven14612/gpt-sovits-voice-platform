from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from models.schemas import DatasetRecord, TaskRecord, TaskStatus
from services import task_service
from ui.task_status import refresh_status, task_status_text
from ui.voice_page import submit_training, voice_rows


class UITaskTests(TestCase):
    def test_training_without_features_is_not_started(self):
        dataset = DatasetRecord(dataset_id="d", display_name="d", source_path=Path("source.wav"), status="reviewed")
        with patch("ui.voice_page.dataset_service.get_dataset", return_value=dataset), \
                patch("ui.voice_page.voice_service.train_voice") as train:
            updates = list(submit_training("d", "valid-id", "音色"))
        self.assertTrue(updates[0][1])
        self.assertFalse(updates[-1][1])
        self.assertIsNone(updates[-1][0])
        self.assertIn("DATASET_NOT_READY", updates[-1][2])
        train.assert_not_called()

    def test_training_rejects_unreviewed_dataset(self):
        dataset = DatasetRecord(dataset_id="d", display_name="d", source_path=Path("source.wav"))
        with patch("ui.voice_page.dataset_service.get_dataset", return_value=dataset), patch("ui.voice_page.voice_service.train_voice") as train:
            result = list(submit_training("d", "valid-id", "音色"))[-1]
        train.assert_not_called()
        self.assertIn("DATASET_NOT_READY", result[2])

    def test_gpu_busy_disables_both_submissions_and_can_recover(self):
        dataset = DatasetRecord(dataset_id="d", display_name="d", source_path=Path("source.wav"))
        with patch("ui.task_status.dataset_service.get_dataset", return_value=dataset), patch("ui.task_status.task_service.list_tasks", return_value=[]):
            task_service.try_acquire_gpu()
            try:
                values = refresh_status(None, "d", False, "")
                self.assertIn("已有任务正在运行", values[0])
                self.assertFalse(values[-1]["interactive"])
                self.assertFalse(values[-2]["interactive"])
                result = list(submit_training("d", "valid-id", "音色"))[-1]
                self.assertIn("GPU_BUSY", result[2])
            finally:
                task_service.release_gpu()
            values = refresh_status(None, "d", False, "")
            self.assertTrue(values[-1]["interactive"])

    def test_persisted_task_states_are_shown_without_percentages(self):
        for status in TaskStatus:
            task = TaskRecord(task_id="task", kind="train_voice", stage="train_gpt", status=status, message="message")
            with self.subTest(status=status), patch("ui.task_status.task_service.list_tasks", return_value=[task]):
                values = refresh_status("task", None, False, "")
                self.assertIn("train_gpt", values[0])
                self.assertIn("message", values[0])
                self.assertNotIn("%", values[0])
        self.assertEqual(task_status_text(None), "当前没有任务。")

    def test_log_summary_reads_only_project_logs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "data" / "logs" / "train" / "t-train_gpt.log"
            log.parent.mkdir(parents=True)
            log.write_text("STAGE: train_gpt\nEXIT CODE: 7\nSTDERR:\ntest failure\n", encoding="utf-8")
            task = TaskRecord(task_id="t", kind="train_voice", log_path=log, status=TaskStatus.FAILED)
            with patch.object(task_service, "PROJECT_ROOT", root):
                stages, text = task_service.task_log_summary(task)
                self.assertEqual(stages[0][:2], ["train_gpt", "7"])
                self.assertIn("test failure", text)
                stages, text = task_service.task_log_summary(task.model_copy(update={"log_path": root / "private.txt"}))
                self.assertEqual(stages, [])
                self.assertIn("目录之外", text)

    def test_voice_library_does_not_promote_drafts(self):
        from models.schemas import VoiceProfile
        draft = VoiceProfile(voice_id="draft", display_name="draft", feature_name="draft", dataset_id="d", engine_profile="local")
        verified = draft.model_copy(update={"voice_id": "verified", "status": "verified"})
        with patch("ui.voice_page.voice_service.list_voices", return_value=[draft, verified]):
            self.assertEqual([row[1] for row in voice_rows()], ["verified"])

    def test_selected_history_controls_details_without_changing_active_task(self):
        active = TaskRecord(task_id="active", kind="synthesis", status=TaskStatus.RUNNING)
        first = TaskRecord(task_id="first", kind="synthesis", status=TaskStatus.SUCCEEDED, message="first detail")
        second = TaskRecord(task_id="second", kind="synthesis", status=TaskStatus.FAILED, message="second detail")
        dataset = DatasetRecord(dataset_id="d", display_name="d", source_path=Path("source.wav"))
        with patch("ui.task_status.task_service.list_tasks", return_value=[active, first, second]), patch("ui.task_status.dataset_service.get_dataset", return_value=dataset):
            for selected, message in (("first", "first detail"), ("second", "second detail")):
                values = refresh_status("active", "d", False, "", selected)
                self.assertEqual(len(values), 5)
                self.assertIn(message, values[0])
                self.assertFalse(values[-1]["interactive"])
                self.assertFalse(values[-2]["interactive"])

    def test_refresh_list_preserves_selection_and_discards_missing_id(self):
        from ui.task_status import refresh_task_picker
        task = TaskRecord(task_id="saved", kind="synthesis")
        with patch("ui.task_status.task_service.list_tasks", return_value=[task]):
            self.assertEqual(refresh_task_picker("saved")["value"], "saved")
            self.assertIsNone(refresh_task_picker("missing")["value"])
