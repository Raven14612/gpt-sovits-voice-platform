import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from models.schemas import AppError, VoiceProfile
from services import voice_service
from ui import result_page, voice_page


def profile(**changes):
    return VoiceProfile(voice_id="raven", display_name="小渡鸦", feature_name="raven",
                        dataset_id="dataset-one", engine_profile="local", status="verified").model_copy(update=changes)


class VoiceLibraryTests(TestCase):
    def test_delete_restore_preserves_files_other_records_and_unknown_fields(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            weight = root / "voice.pth"
            weight.write_bytes(b"keep-original-weight")
            audio = root / "result.wav"
            audio.write_bytes(b"keep-original-output")
            item = profile(gpt_weight=weight, sovits_weight=weight).model_dump(mode="json")
            item["custom_note"] = "keep"
            other = profile(voice_id="other").model_dump(mode="json")
            index = root / "voices.json"
            index.write_text(json.dumps([item, other]), encoding="utf-8")
            with patch.object(voice_service, "try_acquire_gpu"), patch.object(voice_service, "release_gpu"):
                voice_service.set_voice_deleted("raven", True, index)
                self.assertEqual(json.loads(index.read_text(encoding="utf-8"))[0]["status"], "deleted")
                voice_service.set_voice_deleted("raven", False, index)
            self.assertEqual(json.loads(index.read_text(encoding="utf-8")), [item, other])
            self.assertEqual(weight.read_bytes(), b"keep-original-weight")
            self.assertEqual(audio.read_bytes(), b"keep-original-output")

    def test_failed_atomic_replace_preserves_index_and_releases_lock(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "voices.json"
            before = json.dumps([profile().model_dump(mode="json")]).encode()
            index.write_bytes(before)
            with patch.object(voice_service, "try_acquire_gpu"), patch.object(voice_service, "release_gpu") as release, \
                    patch.object(voice_service.os, "replace", side_effect=OSError("disk busy")):
                with self.assertRaises(OSError):
                    voice_service.set_voice_deleted("raven", True, index)
            release.assert_called_once()
            self.assertEqual(index.read_bytes(), before)
            self.assertEqual(list(index.parent.iterdir()), [index])

    def test_corrupt_index_is_never_replaced(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "voices.json"
            index.write_bytes(b"broken-json")
            with patch.object(voice_service, "try_acquire_gpu"), patch.object(voice_service, "release_gpu"):
                with self.assertRaises(AppError) as caught:
                    voice_service.set_voice_deleted("raven", True, index)
            self.assertEqual(caught.exception.code, "VOICE_INDEX_INVALID")
            self.assertEqual(index.read_bytes(), b"broken-json")

    def test_gpu_busy_does_not_write_or_release_someone_elses_lock(self):
        with patch.object(voice_service, "try_acquire_gpu", side_effect=AppError("GPU_BUSY", "busy")), \
                patch.object(voice_service, "_write_voice_data") as write, \
                patch.object(voice_service, "release_gpu") as release:
            with self.assertRaises(AppError):
                voice_service.set_voice_deleted("raven", True)
        write.assert_not_called()
        release.assert_not_called()

    def test_restore_missing_weights_stays_deleted(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "voices.json"
            before = json.dumps([profile(status="deleted").model_dump(mode="json")])
            index.write_text(before, encoding="utf-8")
            with patch.object(voice_service, "try_acquire_gpu"), patch.object(voice_service, "release_gpu"):
                with self.assertRaises(AppError) as caught:
                    voice_service.set_voice_deleted("raven", False, index)
            self.assertEqual(caught.exception.code, "VOICE_WEIGHTS_MISSING")
            self.assertEqual(index.read_text(encoding="utf-8"), before)

    def test_deleting_selection_clears_picker_but_keeps_unrelated_selection(self):
        with patch.object(voice_service, "set_voice_deleted"), \
                patch.object(voice_page, "voice_choices", return_value=[("Other", "other")]):
            removed = voice_page.change_library_voice("raven", True, 2, "raven")
            self.assertEqual(removed[0], 3)
            self.assertIsNone(removed[1]["value"])
            self.assertIsNone(removed[2])
            self.assertEqual(voice_page.change_library_voice("raven", True, 2, "other")[2], "other")

    def test_history_labels_keep_provenance_for_deleted_voice_and_missing_sources(self):
        records = [{"voice_id": "raven", "text": "同一句话", "result_id": "result-12345678",
                    "source_snapshot": {"voice_name": "小渡鸦", "dataset_name": "能天使校对音频"}},
                   {"voice_id": "gone", "text": "同一句话", "result_id": "result-87654321"}]
        with patch.object(result_page.history_service, "list_history", return_value=records), \
                patch.object(voice_service, "list_voices", return_value=[profile(status="deleted")]), \
                patch.object(result_page, "dataset_names", return_value={"dataset-one": "能天使校对音频"}):
            choices = result_page.result_choices()
        self.assertEqual(choices[0], ("小渡鸦［能天使校对音频］ · 同一句话 · 12345678", "result-12345678"))
        self.assertIn("来源未记录", choices[1][0])
        self.assertEqual(choices[1][1], "result-87654321")

    def test_library_html_escapes_names_and_ids(self):
        markup = voice_page.voice_row_html(profile(display_name='<img src=x onerror="bad">'), {"dataset-one": "<script>bad</script>"})
        self.assertNotIn("<img", markup)
        self.assertNotIn("<script>", markup)
        self.assertIn("&lt;script&gt;", markup)

    def test_archive_click_directly_updates_content_even_for_same_selection(self):
        from app import build_app
        from gradio.state_holder import SessionState
        record = profile()
        with patch("ui.layout._status_markdown", return_value="环境状态"), \
                patch.object(voice_service, "list_voices", return_value=[record]), \
                patch.object(voice_service, "get_voice", return_value=record), \
                patch.object(voice_page, "dataset_names", return_value={"dataset-one": "音频来源"}):
            app = build_app()
            session = SessionState(app)
            callbacks = [f for f in app.fns.values() if f.fn is voice_page.show_voice_archive]
            self.assertEqual(len(callbacks), 1)
            fn = callbacks[0]
            self.assertEqual(fn.inputs[0].label, "显示音色")
            self.assertEqual(fn.outputs[1].elem_id, "voice-archive")
            self.assertEqual(fn.outputs[2].label, "音色档案")
            async def exercise():
                for _ in range(2):
                    result = await app.process_api(fn, ["raven"], state=session)
                    self.assertTrue(result["data"][1]["open"])
                    self.assertIn("小渡鸦", result["data"][2])
                    self.assertIn("音频来源", result["data"][2])
                    self.assertIn("已打开", result["data"][3])
                with patch.object(voice_service, "get_voice", return_value=None):
                    missing = await app.process_api(fn, ["raven"], state=session)
                    self.assertIn("已不存在", missing["data"][2])
                    self.assertNotIn("小渡鸦", missing["data"][2])
            asyncio.run(exercise())

    def test_picker_groups_keep_all_choices_and_clear_stale_selections(self):
        records = [profile(voice_id=f"active-{i}") for i in range(4)] + [profile(voice_id=f"deleted-{i}", status="deleted") for i in range(3)]
        with patch.object(voice_service, "list_voices", return_value=records):
            active, deleted, selected = voice_page.refresh_library_pickers("active-2", "deleted-1")
            self.assertEqual(len(active["choices"]), 4)
            self.assertEqual(len(deleted["choices"]), 3)
            self.assertEqual(selected, "active-2")
            self.assertEqual(deleted["value"], "deleted-1")
            active, deleted, selected = voice_page.refresh_library_pickers("deleted-1", "active-2")
            self.assertIsNone(active["value"])
            self.assertIsNone(deleted["value"])
            self.assertIsNone(selected)

    def test_deleted_archive_does_not_select_voice_for_synthesis(self):
        with patch.object(voice_service, "get_voice", return_value=profile(status="deleted")), \
                patch.object(voice_page, "dataset_names", return_value={}):
            selected, panel, detail, message = voice_page.show_voice_archive("raven")
            self.assertEqual(selected, {"__type__": "update"})
            self.assertTrue(panel["open"])
            self.assertIn("已删除", detail)

    def test_preview_buttons_follow_record_status(self):
        for status in ("verified", "deleted", "draft"):
            with self.subTest(status=status), patch.object(voice_service, "get_voice", return_value=profile(status=status)), \
                    patch.object(voice_page, "dataset_names", return_value={}):
                self.assertEqual(voice_page.preview_available_voice("raven")[1]["interactive"], status == "verified")
                self.assertEqual(voice_page.preview_deleted_voice("raven")[2]["interactive"], status == "deleted")

    def test_purge_removes_only_deleted_record_and_cannot_be_restored(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "voices.json"
            other = profile(voice_id="other").model_dump(mode="json")
            other["custom_note"] = "preserve"
            index.write_text(json.dumps([profile(status="deleted").model_dump(mode="json"), other]), encoding="utf-8")
            pending = voice_service.prepare_voice_purge("raven", index)
            with patch.object(voice_service, "try_acquire_gpu"), patch.object(voice_service, "release_gpu"):
                voice_service.purge_voice("raven", pending["fingerprint"], index)
                self.assertIsNone(voice_service.get_voice("raven", index))
                self.assertEqual(json.loads(index.read_text(encoding="utf-8")), [other])
                with self.assertRaises(AppError) as caught:
                    voice_service.set_voice_deleted("raven", False, index)
                self.assertEqual(caught.exception.code, "VOICE_MISSING")

    def test_purge_rejects_active_or_changed_record(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "voices.json"
            item = profile(status="deleted").model_dump(mode="json")
            index.write_text(json.dumps([item]), encoding="utf-8")
            pending = voice_service.prepare_voice_purge("raven", index)
            with patch.object(voice_service, "try_acquire_gpu"), patch.object(voice_service, "release_gpu"):
                for status in ("deleted", "verified"):
                    item["status"] = status
                    item["display_name"] = "changed"
                    before = json.dumps([item])
                    index.write_text(before, encoding="utf-8")
                    with self.assertRaises(AppError):
                        voice_service.purge_voice("raven", pending["fingerprint"], index)
                    self.assertEqual(index.read_text(encoding="utf-8"), before)

    def test_purge_write_failure_preserves_record(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "voices.json"
            before = json.dumps([profile(status="deleted").model_dump(mode="json")])
            index.write_text(before, encoding="utf-8")
            pending = voice_service.prepare_voice_purge("raven", index)
            with patch.object(voice_service, "try_acquire_gpu"), patch.object(voice_service, "release_gpu") as release, \
                    patch.object(voice_service.os, "replace", side_effect=OSError("busy")):
                with self.assertRaises(OSError):
                    voice_service.purge_voice("raven", pending["fingerprint"], index)
            self.assertEqual(index.read_text(encoding="utf-8"), before)
            release.assert_called_once()

    def test_purge_ui_requires_matching_confirmation_and_clears_it(self):
        pending = {"voice_id": "raven", "fingerprint": "test"}
        with patch.object(voice_service, "purge_voice") as purge, \
                patch.object(voice_page, "voice_choices", return_value=[("Other", "other")]):
            for value, selected in ((None, "raven"), (pending, "other")):
                result = voice_page.confirm_voice_purge(value, selected, 3, "other")
                self.assertIn("VOICE_CHANGED", result[3])
                self.assertIsNone(result[6])
            purge.assert_not_called()
            result = voice_page.confirm_voice_purge(pending, "raven", 3, "other")
            purge.assert_called_once_with("raven", "test")
            self.assertEqual(result[0], 4)
            self.assertEqual(result[2], "other")
            self.assertIsNone(result[6])
            self.assertFalse(result[7]["visible"])
