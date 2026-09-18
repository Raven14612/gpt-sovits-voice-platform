"""Opt-in real CPU model smoke test. Only temporary constructed datasets are written."""
import json
from contextlib import ExitStack
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.emotion_classifier import EmotionClassifier
from models.schemas import DatasetRecord
from scripts.prepare_emotion_model import SAMPLES
from services import dataset_service, emotion_service
from services.path_migration import atomic_write, encoded


def main():
    started = time.monotonic()
    probe = emotion_service.probe_emotion_model()
    assert probe["available"], probe
    classifier = EmotionClassifier().load()
    ordered = classifier.predict(SAMPLES[:4], batch_size=3)
    separate = [classifier.predict([text])[0] for text in SAMPLES[:4]]
    assert all(max(a, key=a.get) == max(b, key=b.get) for a, b in zip(ordered, separate))
    report = dict(model_version=classifier.manifest["model_version"], format=classifier.manifest["format"],
                  providers=classifier.session.get_providers(), batch_order_verified=True)
    with TemporaryDirectory(prefix="emotion-real-", dir=ROOT / "data/tmp") as temporary, ExitStack() as stack:
        root = Path(temporary).resolve()
        index = root / "data/index/datasets.json"
        for module in (emotion_service, dataset_service):
            stack.enter_context(patch.object(module, "PROJECT_ROOT", root))
        stack.enter_context(patch.object(dataset_service, "DATASET_INDEX", index))
        stack.enter_context(patch("services.storage_lock.PROJECT_ROOT", root))
        stack.enter_context(patch("services.task_service.try_acquire_gpu", side_effect=AssertionError("CPU model must not acquire GPU")))
        (root / "config").mkdir()
        shutil.copyfile(ROOT / "config/emotion-model.local.json", root / "config/emotion-model.local.json")
        base = root / "data/datasets/real-cpu-test"
        slices = base / "slices"
        slices.mkdir(parents=True)
        rows = []
        for i, text in enumerate(SAMPLES):
            audio = slices / f"{i:03}.wav"
            with wave.open(str(audio), "wb") as output:
                output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                output.writeframes(b"\0\0" * 160)
            rows.append([audio.relative_to(root).as_posix(), text, "neutral"])
        source = base / "source.wav"
        shutil.copyfile(slices / "000.wav", source)
        transcript = base / "slices.list"
        transcript.write_text("\n".join(f"{r[0]}|speaker|zh|{r[1]}" for r in rows), encoding="utf-8")
        dataset_service.upsert_dataset(DatasetRecord(dataset_id="real-cpu-test", display_name="临时真实CPU验证",
            source_path=source, list_path=transcript, slice_dir=slices, status="transcribed"), index)
        inference_started = time.monotonic()
        suggestions = emotion_service.suggest_emotions("real-cpu-test")
        report["suggestion_seconds"] = round(time.monotonic()-inference_started, 2)
        assert len(suggestions.items) == len(SAMPLES)
        before_save = dataset_service.get_dataset("real-cpu-test", index)
        assert before_save.emotions_path is None and before_save.status == "transcribed"
        # Protect an explicit human edit while accepting eligible suggestions.
        rows[0][1:] = ["这是一条人工修改的文本。", "sad"]
        updated = emotion_service.apply_suggestions_to_rows("real-cpu-test", rows, high_confidence_only=True,
                                                          protected_paths=[rows[0][0]])
        assert updated[0] == rows[0]
        accepted = emotion_service.load_suggestions("real-cpu-test")
        report["accepted"] = sum(i.accepted for i in accepted.items)
        assert report["accepted"] > 0
        assert all(not i.accepted for i in accepted.items if i.requires_review)
        saved = dataset_service.save_corrections("real-cpu-test", updated, index_path=index, data_root=root / "data/datasets")
        labels = json.loads(saved.emotions_path.read_text(encoding="utf-8"))
        assert len(labels) == len(SAMPLES) and set(labels.values()) <= {"neutral", "happy", "sad"}
        assert saved.feature_manifest is None and saved.emotion_suggestions_path is None
        child = subprocess.run([sys.executable, "-c", "from pathlib import Path; import json,sys; "
            "from services import dataset_service as ds; ds.PROJECT_ROOT=Path(sys.argv[1]); "
            "print(json.dumps(ds.load_corrections('real-cpu-test',Path(sys.argv[2])),ensure_ascii=True))",
            str(root), str(index)], cwd=ROOT, capture_output=True, text=True, check=True, timeout=30)
        assert json.loads(child.stdout) == updated
        report.update(samples=len(SAMPLES), manual_edit_preserved=True, formal_labels_only_after_confirmation=True,
                      restart_reload_verified=True, unsupported_labels_not_accepted=True, gpu_used=False,
                      feature_extraction="not performed", human_audio_review="not applicable to text model test")
    report["total_seconds"] = round(time.monotonic()-started, 2)
    target = ROOT / "data/logs/diagnostics/emotion-model-real-validation.json"
    atomic_write(target, encoded(report))
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
