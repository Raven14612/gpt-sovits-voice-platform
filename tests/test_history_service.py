from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from models.schemas import AppError

from services.history_service import get_result_output, list_history
from models.schemas import GenerationRecord
from services import history_service


class HistoryServiceTests(TestCase):
    def test_empty_project_history(self) -> None:
        self.assertIsInstance(list_history(), list)

    def test_result_selection_rejects_failed_or_external_outputs(self):
        for record in ({"result_id": "r", "status": "failed", "output_path": "data/outputs/missing.wav"},
                       {"result_id": "r", "status": "succeeded", "output_path": "../private.txt"}):
            with patch("services.history_service._read", return_value=[record]):
                with self.assertRaises(AppError) as ctx:
                    get_result_output("r")
                self.assertEqual(ctx.exception.code, "OUTPUT_INVALID")
                self.assertIsNone(get_result_output("missing"))

    def test_add_history_stores_project_relative_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "data" / "outputs" / "result.wav"
            output.parent.mkdir(parents=True)
            import wave
            with wave.open(str(output), "wb") as wav:
                wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\0\0" * 160)
            index = root / "data" / "index" / "history.json"
            record = GenerationRecord(result_id="r", voice_id="v", text="测试", output_path=output,
                                      status="succeeded")
            with patch.object(history_service, "PROJECT_ROOT", root), \
                    patch.object(history_service, "HISTORY_INDEX", index), \
                    patch.object(history_service, "OUTPUT_ROOT", output.parent):
                history_service.add_history(record)
                saved = history_service.list_history()[0]
            self.assertEqual(saved["output_path"], "data/outputs/result.wav")
