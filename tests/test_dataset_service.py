from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from models.schemas import AppError, DatasetRecord
from services.dataset_service import delete_dataset, get_dataset, list_datasets, upsert_dataset


class DatasetServiceTests(TestCase):
    def test_concurrent_writes_do_not_lose_records(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "datasets.json"
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda i: upsert_dataset(DatasetRecord(dataset_id=str(i), display_name=str(i),
                              source_path=Path("source.wav")), index), range(24)))
            self.assertEqual(len(list_datasets(index)), 24)

    def test_corruption_and_failed_replace_preserve_original(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "datasets.json"
            record = DatasetRecord(dataset_id="d", display_name="test", source_path=Path("source.wav"))
            index.write_text("broken json")
            with self.assertRaises(AppError):
                upsert_dataset(record, index)
            self.assertEqual(index.read_text(), "broken json")
            index.write_text("[]")
            with patch("services.dataset_service.os.replace", side_effect=PermissionError("blocked")):
                with self.assertRaises(PermissionError):
                    upsert_dataset(record, index)
            self.assertEqual(index.read_text(), "[]")
            self.assertEqual(list(index.parent.glob("datasets-*.json")), [])

    def test_atomic_upsert_get_delete(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "datasets.json"
            record = DatasetRecord(dataset_id="d1", display_name="测试", source_path=Path("input.wav"))
            upsert_dataset(record, index)
            self.assertEqual(get_dataset("d1", index).display_name, "测试")
            self.assertEqual(len(list_datasets(index)), 1)
            self.assertTrue(delete_dataset("d1", index))
            self.assertEqual(list_datasets(index), [])
