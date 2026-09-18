from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.prepare_emotion_model import license_notice, mapped, SAMPLES


class EmotionExportTests(TestCase):
    def test_license_preserves_provenance_without_inventing_author_notice(self):
        with TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "README.md").write_text("---\nlicense: mit\n---\nModel card", encoding="utf-8")
            notice = license_notice(source, "a" * 40)
            self.assertIn("license: mit", notice)
            self.assertIn("No separate upstream LICENSE", notice)
            self.assertNotIn("Copyright (c)", notice)
            (source / "README.md").write_text("No licensing information", encoding="utf-8")
            with self.assertRaises(ValueError):
                license_notice(source, "a" * 40)

    def test_validation_covers_required_sample_count_and_product_labels(self):
        self.assertGreaterEqual(len(set(SAMPLES)), 30)
        self.assertEqual([mapped(label) for label in ("neutral", "concern", "happy", "angry", "sad", "question", "surprise", "disgust")],
                         ["neutral", "neutral", "happy", "neutral", "sad", "neutral", "neutral", "neutral"])
