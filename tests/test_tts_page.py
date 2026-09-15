from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from models.schemas import AppError
from ui import tts_page
from ui.result_page import refresh_results


class TTSPageTests(TestCase):
    def test_submit_synthesis_displays_service_output(self):
        with TemporaryDirectory() as directory:
            output_root = Path(directory)

            def synthesize(**kwargs):
                output = Path(kwargs["output_path"])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"RIFFreal-wav")
                return output

            with patch.object(tts_page, "OUTPUT_ROOT", output_root), \
                    patch("ui.tts_page.tts_service.synthesize", side_effect=synthesize) as service, \
                    patch("ui.tts_page.history_service.add_history") as add_history:
                result_id, audio, status = tts_page.submit_synthesis(
                    "citlali", "测试文本", "neutral", 1.1, 0.3
                )

            self.assertTrue(result_id.startswith("tts-"))
            self.assertTrue(Path(audio).is_file())
            self.assertIn("成功", status)
            self.assertEqual(service.call_args.kwargs["speed_factor"], 1.1)
            # Persistence belongs to the service, never to the UI.
            add_history.assert_not_called()

    def test_submit_synthesis_failure_is_not_published(self):
        with patch("ui.tts_page.tts_service.synthesize",
                   side_effect=AppError("SYNTHESIS_FAILED", "引擎失败")), \
                patch("ui.tts_page.history_service.add_history") as add_history:
            result_id, audio, status = tts_page.submit_synthesis(
                "citlali", "测试文本", "neutral", 1.0, 0.3
            )

        self.assertIsNone(result_id)
        self.assertIsNone(audio)
        self.assertIn("SYNTHESIS_FAILED", status)
        add_history.assert_not_called()

    def test_submit_requires_voice_and_text(self):
        self.assertIn("选择音色", tts_page.submit_synthesis(None, "文本", None, 1.0, 0.3)[2])
        self.assertIn("输入", tts_page.submit_synthesis("citlali", "", "neutral", 1.0, 0.3)[2])

    def test_result_page_refresh_loads_current_audio(self):
        with patch("ui.result_page.result_choices", return_value=[("测试", "r")]), \
                patch("ui.result_page.select_result", return_value=("r", "result.wav", "")):
            dropdown, audio, message = refresh_results("r")
        self.assertEqual(dropdown["value"], "r")
        self.assertEqual(audio, "result.wav")
        self.assertEqual(message, "")
