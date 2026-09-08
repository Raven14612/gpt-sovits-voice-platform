from unittest import TestCase
from unittest.mock import patch
from models.schemas import AppError

from services.history_service import get_result_output, list_history


class HistoryServiceTests(TestCase):
    def test_empty_project_history(self) -> None:
        self.assertIsInstance(list_history(), list)

    def test_result_selection_rejects_failed_or_external_outputs(self):
        for record in ({"result_id": "r", "status": "failed", "output_path": "data/outputs/missing.wav"},
                       {"result_id": "r", "status": "succeeded", "output_path": "../private.txt"}):
            with patch("services.history_service.list_history", return_value=[record]):
                with self.assertRaises(AppError) as ctx:
                    get_result_output("r")
                self.assertEqual(ctx.exception.code, "OUTPUT_INVALID")
                self.assertIsNone(get_result_output("missing"))
