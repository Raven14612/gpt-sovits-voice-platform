"""Read-only data checks after moving the application; no training or synthesis."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services import dataset_service, voice_service, history_service
from services.engine_service import load_engine_config
from services.project_paths import resolve_project_path


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def check():
    cfg = load_engine_config()
    checks = [{"kind": "engine", "engine_root": str(cfg.engine_root),
               "python_path": str(cfg.python_path),
               "passed": cfg.python_path.is_file() and cfg.python_path.is_relative_to(ROOT)
               and cfg.engine_root.is_relative_to(ROOT)}]
    for dataset in dataset_service.list_datasets(strict=True):
        manifest = json.loads(dataset.feature_manifest.read_text(encoding="utf-8"))
        rows = dataset_service.load_corrections(dataset.dataset_id)
        row_paths = {resolve_project_path(row[0]) for row in rows}
        wavs = {p.resolve() for p in dataset.slice_dir.glob("*.wav")}
        inputs = [resolve_project_path(p) for p in manifest["inputs_sha256"]]
        hashes = all(p.is_file() and sha(p) == digest for p, digest in
                     zip(inputs, manifest["inputs_sha256"].values()))
        outputs = [resolve_project_path(item["path"]) for item in manifest["outputs"]]
        output_sizes = all(p.is_file() and p.stat().st_size == item["bytes"]
                           for p, item in zip(outputs, manifest["outputs"]))
        checks.append({"kind": "dataset", "dataset_id": dataset.dataset_id,
                       "rows": len(rows), "input_hashes_match": hashes,
                       "feature_sizes_match": output_sizes,
                       "passed": hashes and output_sizes and row_paths == wavs
                       and all(p.is_relative_to(ROOT) and p.is_file()
                               for p in [*row_paths, *inputs, *outputs])})
    for voice in voice_service.list_voice_profiles():
        paths = [voice.gpt_weight, voice.sovits_weight, *[r.audio_path for r in voice.references]]
        checks.append({"kind": "voice", "voice_id": voice.voice_id,
                       "passed": all(p and p.is_file() and p.is_relative_to(ROOT) for p in paths)})
    valid_history = history_service.list_history()
    checks.append({"kind": "history", "valid_outputs": len(valid_history),
                   "passed": all(Path(history_service.get_result_output(h["result_id"])).is_relative_to(ROOT)
                                 for h in valid_history)})
    return {"scope": "path_and_existing_data_only", "root": str(ROOT),
            "passed": all(c["passed"] for c in checks), "checks": checks,
            "training_executed": False, "synthesis_executed": False}


if __name__ == "__main__":
    report = check()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
