"""Publisher-only ONNX export; run in a separate torch/transformers/onnx environment.

The upstream commit must be supplied as a full immutable SHA, never main/latest.
No code from the model repository is executed. The desktop never runs this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile
import importlib.metadata

MODEL_ID = "Johnson8187/Chinese-Emotion-Small"
SOURCE_FILES = ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
                "special_tokens_map.json", "added_tokens.json", "spm.model", "README.md")
SAMPLES = [
    "今天按时完成了工作。", "会议安排在明天下午。", "桌上放着一本书。", "请把文件发给我。", "公交车到站了。",
    "我终于通过考试了，太开心了！", "收到你的礼物，我很高兴。", "我们赢得了比赛！", "今天真是美好的一天。", "好久不见，见到你真好。",
    "想到再也见不到他，我很难过。", "我努力了很久却还是失败了。", "眼泪忍不住掉下来。", "离别让我心里空落落的。", "这段回忆令人悲伤。",
    "你怎么能这样欺骗我！", "这件事太让人生气了。", "请不要再打扰我了！", "居然会发生这样的事？", "没想到你也来了！",
    "我害怕一个人走夜路。", "听到这个消息我很担心。", "这个味道让我恶心。", "真不想再看见这种东西。", "记得多喝水，照顾好自己。",
    "你现在身体好点了吗？", "为什么会出现这个问题？", "你能告诉我答案吗？", "我有点失落，但也为你感到高兴。", "天气预报说明天有雨。",
    "并没有什么值得开心的事情。", "别难过，我们还有机会。",
]


def mapped(label):
    return {"happy": "happy", "joy": "happy", "sad": "sad", "sadness": "sad"}.get(label.lower(), "neutral")


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def license_notice(source, revision):
    """Retain upstream evidence; never invent an upstream copyright notice."""
    card = (source / "README.md").read_text(encoding="utf-8-sig")
    if not re.search(r"(?m)^license:\s*mit\s*$", card):
        raise ValueError("The local model card must explicitly declare MIT licensing")
    return (f"License evidence for {MODEL_ID}\n"
            f"User-supplied revision: {revision}\n"
            f"Source: https://huggingface.co/{MODEL_ID}/blob/{revision}/README.md\n"
            "The downloaded model card declares: license: mit.\n"
            "No separate upstream LICENSE or copyright notice was supplied. This is a generated\n"
            "provenance notice, not a license file copied from the author. Retain the model card\n"
            "and verify upstream notices before redistributing this resource.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Publisher-reviewed 40-character upstream commit SHA")
    parser.add_argument("--source", type=Path, help="Downloaded model directory; avoids network access")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--labels", type=Path, help="JSON array of reviewed canonical English labels, in upstream class order")
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("revision must be an immutable commit SHA")
    if not 1 <= args.threads <= 16:
        parser.error("threads must be between 1 and 16")
    import numpy as np
    import torch
    import onnxruntime as ort
    from onnxruntime.quantization import quantize_dynamic, QuantType
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    from huggingface_hub import hf_hub_download

    torch.set_num_threads(args.threads)
    source_hashes = {name: sha(args.source / name) for name in SOURCE_FILES if (args.source / name).is_file()} if args.source else {}

    args.output.mkdir(parents=True, exist_ok=True)
    final = args.output / "emotion-zh-v1.zip"
    if final.exists():
        raise SystemExit("Output exists; select a fresh output directory.")
    with tempfile.TemporaryDirectory(prefix="emotion-export-", dir=args.output) as temporary:
        work = Path(temporary)
        bundle = work / "emotion-zh-v1"
        bundle.mkdir()
        source = str(args.source.resolve()) if args.source else MODEL_ID
        tokenizer = AutoTokenizer.from_pretrained(source, revision=None if args.source else args.revision,
                                                  trust_remote_code=False, use_fast=True,
                                                  local_files_only=bool(args.source))
        model = AutoModelForSequenceClassification.from_pretrained(source, revision=None if args.source else args.revision,
                                                                   trust_remote_code=False, use_safetensors=True,
                                                                   local_files_only=bool(args.source)).cpu().eval()
        upstream_labels = [model.config.id2label[i] for i in range(model.config.num_labels)]
        labels = json.loads(args.labels.read_text(encoding="utf-8-sig")) if args.labels else upstream_labels
        if (len(labels) != len(upstream_labels) or len(set(labels)) != len(labels)
                or any(not re.fullmatch(r"[a-z]+", label) for label in labels)
                or not {"neutral"}.issubset(labels) or not {"happy", "joy"}.intersection(labels)
                or not {"sad", "sadness"}.intersection(labels)):
            raise SystemExit("Supply reviewed canonical --labels in exact upstream class order; never guess LABEL_n meanings.")
        contexts = [f"[上文] {SAMPLES[i-1] if i else ''} [当前] {text} [下文] {SAMPLES[i+1] if i+1<len(SAMPLES) else ''}"
                    for i, text in enumerate(SAMPLES)]
        tokens = tokenizer(contexts, max_length=256, truncation=True, padding="max_length", return_tensors="pt")
        names = list(tokens)
        class Logits(torch.nn.Module):
            def __init__(self, classifier):
                super().__init__()
                self.classifier = classifier
            def forward(self, *inputs):
                return self.classifier(**dict(zip(names, inputs))).logits
        with torch.no_grad():
            print("Validating original model on 32 fixed Chinese samples (CPU)...", flush=True)
            expected = np.concatenate([model(**{n: tokens[n][i:i+4] for n in names}).logits.numpy().argmax(axis=1)
                                       for i in range(0, len(SAMPLES), 4)])
            print("Exporting ONNX...", flush=True)
            torch.onnx.export(Logits(model), tuple(tokens[n][:2] for n in names), str(bundle / "model.onnx"),
                              input_names=names, output_names=["logits"], opset_version=17, dynamo=False,
                              dynamic_axes={**{n: {0: "batch", 1: "sequence"} for n in names}, "logits": {0: "batch"}})
        tokenizer.backend_tokenizer.save(str(bundle / "tokenizer.json"))
        # Check the exact standalone tokenizer and CPU session consumed by the client.
        from tokenizers import Tokenizer
        runtime_tokenizer = Tokenizer.from_file(str(bundle / "tokenizer.json"))
        runtime_tokenizer.enable_truncation(max_length=256)
        runtime_tokenizer.enable_padding(length=256, pad_id=tokenizer.pad_token_id, pad_token=tokenizer.pad_token)
        enc = runtime_tokenizer.encode_batch(contexts)
        arrays = {"input_ids": [e.ids for e in enc], "attention_mask": [e.attention_mask for e in enc],
                  "token_type_ids": [e.type_ids for e in enc]}
        feed = {n: np.asarray(arrays[n], dtype=np.int64) for n in names}
        if any(not np.array_equal(feed[n], tokens[n].numpy()) for n in names):
            raise SystemExit("Standalone tokenizer output differs from source tokenizer; no package published.")
        validation_results = {}
        def validate(path):
            options = ort.SessionOptions()
            options.intra_op_num_threads = args.threads
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
            input_names = {item.name for item in session.get_inputs()}
            if not input_names or not input_names.issubset(feed):
                raise ValueError("Unexpected exported model inputs")
            logits = np.concatenate([session.run(None, {n: a[i:i+4] for n, a in feed.items() if n in input_names})[0]
                                     for i in range(0, len(SAMPLES), 4)])
            if logits.shape != (len(SAMPLES), len(labels)) or not np.isfinite(logits).all():
                return 0.0
            predicted = logits.argmax(axis=1)
            validation_results[path.name] = dict(raw_agreement=float(np.mean(expected == predicted)),
                predicted_labels=[labels[int(i)] for i in predicted])
            return sum(mapped(labels[a]) == mapped(labels[b]) for a, b in zip(expected, predicted)) / len(SAMPLES)
        agreement = validate(bundle / "model.onnx")
        if agreement < .95:
            raise SystemExit("FP32 ONNX mapped label agreement below 95%; no package published.")
        format_name = "fp32"
        fp32_agreement = agreement
        print(f"FP32 mapped agreement: {agreement:.2%}; attempting INT8...", flush=True)
        try:
            quantized = work / "int8.onnx"
            quantize_dynamic(str(bundle / "model.onnx"), str(quantized), weight_type=QuantType.QInt8)
            quantized_agreement = validate(quantized)
            if quantized_agreement >= .95:
                shutil.copyfile(quantized, bundle / "model.onnx")
                agreement, format_name = quantized_agreement, "int8"
        except Exception as exc:
            print(f"INT8 validation unavailable ({type(exc).__name__}); retaining validated FP32.")
        if args.source:
            (bundle / "LICENSE.txt").write_text(license_notice(args.source, args.revision), encoding="utf-8")
        else:
            license_path = hf_hub_download(MODEL_ID, "LICENSE", revision=args.revision)
            shutil.copyfile(license_path, bundle / "LICENSE.txt")
        (bundle / "README.txt").write_text(f"Source: https://huggingface.co/{MODEL_ID}\nRevision: {args.revision}\n"
            "Extract emotion-zh-v1 into models/emotion/. CPU semantic suggestions only.\n\n"
            + ((args.source / "README.md").read_text(encoding="utf-8-sig") if args.source else ""), encoding="utf-8")
        manifest = dict(schema_version=1, model_id="emotion-zh-v1", model_version=args.revision,
            upstream_model_id=MODEL_ID, upstream_revision=args.revision, upstream_labels=upstream_labels, labels=labels,
            max_length=256, pad_token_id=tokenizer.pad_token_id, pad_token=tokenizer.pad_token, format=format_name,
            source_verification="local hashes; revision supplied by user" if args.source else "pinned upstream download",
            source_sha256=source_hashes,
            export_versions={name: importlib.metadata.version(name) for name in ("torch", "transformers", "onnx", "onnxruntime", "tokenizers")},
            validation=dict(samples=len(SAMPLES), mapped_agreement=agreement, fp32_mapped_agreement=fp32_agreement),
            files={p.name: dict(bytes=p.stat().st_size, sha256=sha(p)) for p in bundle.iterdir()})
        manifest_path = bundle / "model-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        report = dict(revision=args.revision, source_sha256=source_hashes, export_versions=manifest["export_versions"],
                      selected_format=format_name, mapped_agreement=agreement, results=validation_results,
                      samples=[dict(text=t, context=c, source_label=labels[int(i)]) for t, c, i in zip(SAMPLES, contexts, expected)])
        archive_path = work / "emotion-zh-v1.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in bundle.iterdir():
                archive.write(path, "emotion-zh-v1/" + path.name)
        archive_path.replace(final)
        (args.output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(dict(package=str(final), manifest_sha256=sha(manifest_path), revision=args.revision,
                              format=format_name, mapped_agreement=agreement), ensure_ascii=False))


if __name__ == "__main__":
    main()
