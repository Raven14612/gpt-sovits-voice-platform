import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services import dataset_service
from services.project_paths import resolve_project_path


class ProjectMigrationTests(unittest.TestCase):
    def test_archived_transcript_resolves_to_new_root_without_changing_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "new root"
            old = Path(tmp).resolve() / "old root"
            (root / "config").mkdir(parents=True)
            (root / "config/path-migration.json").write_text(json.dumps({"aliases": [
                {"old_root": str(old), "new_relative_root": "."}
            ]}), encoding="utf-8")
            target = root / "data/slice.wav"
            target.parent.mkdir()
            target.write_bytes(b"fixture")
            transcript = root / "corrected.list"
            transcript.write_text(str(old / "data/slice.wav") + "|speaker|zh|text\n", encoding="utf-8")
            before = hashlib.sha256(transcript.read_bytes()).hexdigest()
            with patch.object(dataset_service, "PROJECT_ROOT", root):
                rows = dataset_service._read_transcript(transcript)
            self.assertEqual(Path(rows[0][0]), target)
            self.assertTrue(Path(rows[0][0]).is_file())
            self.assertEqual(hashlib.sha256(transcript.read_bytes()).hexdigest(), before)

    def test_relative_path_uses_explicit_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "project"
            self.assertEqual(resolve_project_path("data/file", root=root), root / "data/file")

    def test_alias_is_a_directory_boundary_not_string_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "new"
            old = Path(tmp).resolve() / "old"
            (root / "config").mkdir(parents=True)
            (root / "config/path-migration.json").write_text(json.dumps({"aliases": [
                {"old_root": str(old), "new_relative_root": "."}
            ]}), encoding="utf-8")
            unrelated = Path(tmp).resolve() / "older/file.wav"
            self.assertEqual(resolve_project_path(unrelated, root=root), unrelated)
