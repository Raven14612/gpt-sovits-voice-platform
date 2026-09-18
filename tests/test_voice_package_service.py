import json
import shutil
import stat
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import zipfile

from models.schemas import AppError
from services import asset_service, voice_package_service as packages, voice_service
from workshop_server.tests.helpers import make_package


class VoicePackageTests(TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory())).resolve()
        for module in (packages, voice_service):
            self.stack.enter_context(patch.object(module, "PROJECT_ROOT", self.root))
        self.stack.enter_context(patch("services.storage_lock.PROJECT_ROOT", self.root))
        self.index = self.root / "data/index/voices.json"
        self.stack.enter_context(patch.object(voice_service, "VOICE_INDEX", self.index))
        self.package = make_package(self.root / "fixture.rvoice")

    @staticmethod
    def fake_sanitizer(gpt, sovits, output):
        output.mkdir()
        # Distinct bytes prove that registration points to re-saved files.
        (output / "gpt.ckpt").write_bytes(b"sanitized GPT")
        (output / "sovits.pth").write_bytes(b"sanitized SoVITS")

    def test_install_restart_duplicate_export_and_owned_deletion(self):
        with patch.object(packages, "_sanitize", side_effect=self.fake_sanitizer):
            voice = packages.install_voice_package(self.package, origin_workshop_id="test-id")
            self.assertEqual(voice.dataset_id, "")
            self.assertTrue(voice.voice_id.startswith("voice-"))
            self.assertEqual(voice.gpt_weight.read_bytes(), b"sanitized GPT")
            self.assertTrue(voice.references[0].audio_path.is_relative_to(self.root / "data/voices" / voice.voice_id))
            loaded = voice_service.get_voice(voice.voice_id, self.index)
            self.assertEqual(loaded.origin_type, "workshop")
            self.assertIsNone(loaded.usage_verified_at)
            stored = json.loads(self.index.read_text(encoding="utf-8"))[0]
            self.assertFalse(Path(stored["gpt_weight"]).is_absolute())
            with self.assertRaises(AppError) as caught:
                packages.install_voice_package(self.package)
            self.assertEqual(caught.exception.code, "PACKAGE_ALREADY_INSTALLED")
            exported = packages.export_voice_package(voice.voice_id, "作者", "测试简介", "CC BY 4.0", True)
            inspection = packages.inspect_voice_package(exported)
            self.assertNotIn(str(self.root), json.dumps(inspection))
            self.assertNotIn("dataset_id", json.dumps(inspection))
        unrelated = self.root / "data/datasets/local/source.wav"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_bytes(b"untouched")
        original_index = self.root / "data/index/datasets.json"
        asset_service.atomic_json(original_index, [{"dataset_id": "local", "display_name": "用户数据", "source_path": "data/datasets/local/source.wav"}])
        before = original_index.read_bytes()
        plan = asset_service.deletion_plan(voice.voice_id, self.index, self.root)
        self.assertEqual(plan["paths"], [f"data/voices/{voice.voice_id}"])
        asset_service.execute_delete(plan, self.index, self.root)
        self.assertTrue(unrelated.exists())
        self.assertEqual(original_index.read_bytes(), before)
        self.assertEqual(json.loads(self.index.read_text()), [])

    def test_static_rejections(self):
        cases = [dict(extra="../outside.py"), dict(extra="run.py"),
                 dict(transform=lambda m, f: m["files"][0].update(sha256="f"*64)),
                 dict(transform=lambda m, f: f.pop("references/neutral.wav")),
                 dict(transform=lambda m, f: m.update(dataset_id="forbidden")),
                 dict(transform=lambda m, f: m["engine"].update(model_version="v4"))]
        for i, args in enumerate(cases):
            with self.subTest(i=i):
                path = make_package(self.root / f"bad{i}.rvoice", **args)
                with self.assertRaises(AppError):
                    packages.inspect_voice_package(path)
        link = zipfile.ZipInfo("references/happy.wav")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.package, "a") as archive:
            archive.writestr(link, "../../outside")
        with self.assertRaises(AppError):
            packages.inspect_voice_package(self.package)

    def test_bomb_limits_uncompressed_payload(self):
        path = make_package(self.root / "bomb.rvoice", weight_bytes=1024*1024)
        self.assertLess(path.stat().st_size, 10000)
        with self.assertRaises(AppError) as caught:
            packages.inspect_voice_package(path, max_bytes=10000)
        self.assertEqual(caught.exception.code, "PACKAGE_TOO_LARGE")

    def test_sanitizer_and_index_failure_leave_no_registration(self):
        with patch.object(packages, "_sanitize", side_effect=AppError("CHECKPOINT_UNSAFE", "blocked")):
            with self.assertRaises(AppError):
                packages.install_voice_package(self.package)
        self.assertFalse(self.index.exists())
        with patch.object(packages, "_sanitize", side_effect=self.fake_sanitizer), patch.object(
                voice_service, "_write_voice_data", side_effect=PermissionError("blocked")):
            with self.assertRaises(PermissionError):
                packages.install_voice_package(self.package)
        self.assertFalse(self.index.exists())
        self.assertEqual(list((self.root / "data/voices").glob("*")), [])
        self.assertEqual(list((self.root / "data/tmp/voice-packages").glob("*")), [])

    def test_no_rights_and_corrupt_index_fail_closed(self):
        with self.assertRaises(AppError):
            packages.export_voice_package("v", "作者", "简介", "CC BY 4.0", False)
        self.index.parent.mkdir(parents=True)
        self.index.write_text("broken")
        with self.assertRaises(AppError):
            packages.install_voice_package(self.package)
        self.assertEqual(self.index.read_text(), "broken")

    def test_unset_upload_fields_return_readable_validation_error(self):
        for author, description in ((None, 'description'), ('author', None)):
            with self.assertRaises(AppError) as caught:
                packages.export_voice_package('v', author, description, 'CC BY 4.0', True)
            self.assertEqual(caught.exception.code, 'PACKAGE_METADATA_INVALID')
