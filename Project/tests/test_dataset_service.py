from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from models.schemas import DatasetRecord
from services.dataset_service import delete_dataset, get_dataset, list_datasets, upsert_dataset


class DatasetServiceTests(TestCase):
    def test_atomic_upsert_get_delete(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "datasets.json"
            record = DatasetRecord(dataset_id="d1", display_name="测试", source_path=Path("input.wav"))
            upsert_dataset(record, index)
            self.assertEqual(get_dataset("d1", index).display_name, "测试")
            self.assertEqual(len(list_datasets(index)), 1)
            self.assertTrue(delete_dataset("d1", index))
            self.assertEqual(list_datasets(index), [])
