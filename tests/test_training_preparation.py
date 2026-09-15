import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import yaml

from models.schemas import AppError
from services import dataset_service, training_preparation_service as preparation


class TrainingPreparationTests(TestCase):
    def test_unready_dataset_does_not_prepare(self):
        with patch.object(preparation.dataset_service, "get_dataset", return_value=None):
            with self.assertRaises(AppError) as error:
                preparation.prepare_training("missing", "valid-id")
        self.assertEqual(error.exception.code, "DATASET_NOT_READY")

    def test_real_features_prepare_configs_without_training(self):
        dataset_id = os.environ.get("GPT_SOVITS_FEATURE_DATASET")
        if not dataset_id:
            self.skipTest("real extracted feature dataset unavailable")
        record = dataset_service.get_dataset(dataset_id)
        self.assertIsNotNone(record.feature_manifest)
        # Keep authorized real input paths; redirect only new training preparation output.
        with TemporaryDirectory(dir=preparation.PROJECT_ROOT / "data", prefix="prepare-test-") as directory:
            root = Path(directory).resolve()
            original_inside = preparation._inside
            with patch.object(preparation, "PROJECT_ROOT", root), patch.object(preparation, "_inside",
                side_effect=lambda path, target: original_inside(path, dataset_service.DATASET_ROOT)
                if target == root / "data/datasets" else original_inside(path, target)):
                target = preparation.prepare_training(dataset_id, "prepare-test")
            plan = json.loads(target.read_text(encoding="utf-8"))
            self.assertFalse(plan["training_started"])
            self.assertEqual([stage["stage"] for stage in plan["stages"]], ["train_gpt", "train_sovits"])
            s2 = json.loads((target.parent / "s2.json").read_text(encoding="utf-8"))
            s1 = yaml.safe_load((target.parent / "s1.yaml").read_text(encoding="utf-8"))
            self.assertEqual((s2["train"]["epochs"], s1["train"]["epochs"]), (8, 15))
            self.assertFalse(s1["train"]["if_dpo"])
            self.assertEqual(s2["train"]["gpu_numbers"], "0")
            self.assertTrue(Path(s2["data"]["exp_dir"]).is_relative_to(root))
            self.assertEqual(list((target.parent / "GPT_weights").iterdir()), [])
            self.assertEqual(list((target.parent / "SoVITS_weights").iterdir()), [])
