from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from models.schemas import AppError, DatasetRecord
from services import dataset_service
from ui.audio_page import save_table, submit_audio, update_slice


class AudioPageTests(TestCase):
    def test_import_and_save_corrections_preserves_source(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            index, data = root / "index.json", root / "data"
            source = root / "original.list"
            source.write_text("slice.wav|speaker|zh|原识别文本\n", encoding="utf-8")
            dataset_service.upsert_dataset(DatasetRecord(dataset_id="d", display_name="数据", source_path=root / "input.wav"), index)
            record = dataset_service.import_transcript("d", str(source), index_path=index, data_root=data)
            self.assertEqual(record.status, "transcribed")
            rows = dataset_service.load_corrections("d", index)
            self.assertEqual(rows, [["slice.wav", "原识别文本", "neutral"]])
            rows[0][1:] = ["人工校对文本", "happy"]
            saved = dataset_service.save_corrections("d", rows, index_path=index, data_root=data)
            self.assertEqual(saved.status, "reviewed")
            self.assertEqual(dataset_service.load_corrections("d", index), rows)
            self.assertIn("原识别文本", source.read_text(encoding="utf-8"))
            for invalid in ([["other.wav", "文本", "neutral"]], [["slice.wav", "", "neutral"]],
                            [["slice.wav", "文本", "angry"]], []):
                with self.assertRaises(AppError):
                    dataset_service.save_corrections("d", invalid, index_path=index, data_root=data)
                self.assertEqual(dataset_service.get_dataset("d", index), saved)

    def test_invalid_audio_does_not_create_dataset(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "not-audio.txt"
            path.write_text("not audio", encoding="utf-8")
            with self.assertRaises(AppError) as ctx:
                dataset_service.import_audio(str(path), "invalid", index_path=root / "index.json", data_root=root / "data")
            self.assertEqual(ctx.exception.code, "INVALID_AUDIO")
            self.assertFalse((root / "data").exists())

    def test_audio_submit_reports_unimplemented_without_success(self):
        record = DatasetRecord(dataset_id="d", display_name="test", source_path=Path("input.wav"))
        with patch("ui.audio_page.dataset_service.get_dataset", return_value=record):
            task, message = submit_audio("d", 0, None)
            self.assertEqual(task, {"__type__": "update"})
            self.assertIn("NOT_IMPLEMENTED", message)
            self.assertIn("INVALID_AUDIO", submit_audio("d", 5, 2)[1])

    def test_unsaved_row_and_failed_save_are_explicit(self):
        rows = [["slice.wav", "文本", "neutral"]]
        updated, message = update_slice(rows, 0, "修订", "sad")
        self.assertEqual(rows[0][1], "文本")
        self.assertEqual(updated[0][2], "sad")
        self.assertIn("尚未保存", message)
        with patch("ui.audio_page.dataset_service.save_corrections", side_effect=AppError("TRANSCRIPT_INVALID", "invalid")):
            self.assertIn("TRANSCRIPT_INVALID", save_table("d", updated))
