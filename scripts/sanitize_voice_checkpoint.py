"""Model-runtime-only safety gate. Never fall back to unrestricted pickle loading."""
from __future__ import annotations

import argparse
from collections import OrderedDict
import math
from pathlib import Path
from pathlib import PureWindowsPath
import shutil
import sys
import tempfile


class _CheckpointHParams:
    """Inert stand-in for legacy config bags; never import checkpoint code."""
    pass


def _plain_config_bags(value):
    # Called only after bounded, acyclic tree validation.
    if type(value) is _CheckpointHParams:
        value = vars(value)
    if type(value) in (dict, OrderedDict):
        return {_plain_config_bags(k): _plain_config_bags(v) for k, v in value.items()}
    if type(value) in (tuple, list):
        return type(value)(_plain_config_bags(v) for v in value)
    return value


def validate_tree(value, torch, *, depth=0, seen=None):
    if depth > 80:
        raise ValueError("object tree too deep")
    if value is None or type(value) in (str, int, bool):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is torch.Tensor:
        if value.device.type != "cpu" or value.layout != torch.strided:
            raise ValueError("unsupported tensor")
        return
    if type(value) not in (dict, OrderedDict, list, tuple, _CheckpointHParams):
        raise ValueError("unsupported object")
    seen = set() if seen is None else seen
    if id(value) in seen:
        raise ValueError("cyclic object")
    seen.add(id(value))
    try:
        children = list(vars(value).items()) if type(value) is _CheckpointHParams else list(value.items()) if isinstance(value, dict) else value
        for item in children:
            validate_tree(item, torch, depth=depth+1, seen=seen)
    finally:
        seen.remove(id(value))


def sanitize(source, target, role):
    import torch
    def restricted_load(path):
        # Resolve this one legacy name to a local class with no code or hooks.
        # Unknown globals remain forbidden; weights_only is never disabled.
        with torch.serialization.safe_globals([(_CheckpointHParams, "utils.HParams")]):
            return torch.load(path, map_location="cpu", weights_only=True)
    # v2Pro replaces ZIP's first two bytes with 05. Normalize an owned temporary
    # copy before restricted loading, then retain the engine's version marker.
    with Path(source).open("rb") as handle:
        prefix = handle.read(2)
    if prefix == b"05" and role == "sovits":
        with tempfile.TemporaryDirectory(dir=Path(target).parent) as temporary:
            normalized = Path(temporary) / "checkpoint.pth"
            with Path(source).open("rb") as src, normalized.open("xb") as dst:
                src.read(2)
                dst.write(b"PK")
                shutil.copyfileobj(src, dst, 1024 * 1024)
            data = restricted_load(normalized)
    else:
        data = restricted_load(source)
    validate_tree(data, torch)
    data = _plain_config_bags(data)
    if (type(data) not in (dict, OrderedDict) or not isinstance(data.get("config"), dict)
            or not isinstance(data.get("weight"), dict) or not data["weight"]
            or any(type(k) is not str or type(v) is not torch.Tensor for k, v in data["weight"].items())):
        raise ValueError("checkpoint requires config and tensor weight dictionaries")
    config = data["config"]
    required = {"data", "model"} if role == "gpt" else {"data", "train", "model"}
    if not required.issubset(config) or any(not isinstance(config[k], dict) for k in required):
        raise ValueError("missing engine configuration")
    if role == "gpt" and "max_sec" not in config["data"]:
        raise ValueError("GPT max_sec missing")
    if role == "sovits" and (not {"filter_length", "sampling_rate", "hop_length", "win_length", "n_speakers"}.issubset(config["data"])
                             or "segment_size" not in config["train"]):
        raise ValueError("SoVITS audio configuration missing")
    if Path(source).resolve() == Path(target).resolve() or Path(target).exists():
        raise ValueError("target must be a fresh local file")
    # Only engine-required dictionaries survive; optimizer/training objects are omitted.
    def portable(value):
        if isinstance(value, dict):
            return {k: portable(v) for k, v in value.items() if k not in {
                "dataset_id", "train_semantic_path", "train_phoneme_path", "training_files", "validation_files",
                "output_dir", "save_weight_dir", "half_weights_save_dir", "exp_dir", "s2_ckpt_dir",
                "pretrained_s1", "pretrained_s2G", "pretrained_s2D"}}
        if isinstance(value, (tuple, list)):
            return type(value)(portable(v) for v in value)
        if isinstance(value, str) and (Path(value).is_absolute() or PureWindowsPath(value).is_absolute()):
            return ""
        return value
    torch.save({"config": portable(config), "weight": dict(data["weight"])}, target)
    if role == "sovits":
        with Path(target).open("r+b") as handle:
            handle.write(b"05")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpt", required=True, type=Path)
    parser.add_argument("--sovits", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        args.output.mkdir(parents=True, exist_ok=False)
        sanitize(args.gpt, args.output / "gpt.ckpt", "gpt")
        sanitize(args.sovits, args.output / "sovits.pth", "sovits")
    except Exception:
        print("CHECKPOINT_UNSAFE: 权重安全预检未通过。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
