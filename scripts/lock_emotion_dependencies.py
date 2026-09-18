"""Resolve publisher-selected UI wheels to hashes; run only when updating the lock."""
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PINS = {"onnxruntime": "1.23.2", "tokenizers": "0.22.1", "coloredlogs": "15.0.1",
        "humanfriendly": "10.0", "flatbuffers": "25.9.23", "protobuf": "6.33.1",
        "sympy": "1.14.0", "mpmath": "1.3.0"}


def main():
    from packaging.tags import sys_tags
    from packaging.utils import parse_wheel_filename
    tags = list(sys_tags())
    lines = []
    for name, version in PINS.items():
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
            data = json.load(response)
        candidates = []
        for file in data["urls"]:
            if not file["filename"].endswith(".whl"):
                continue
            wheel_tags = parse_wheel_filename(file["filename"])[3]
            ranks = [i for i, tag in enumerate(tags) if tag in wheel_tags]
            if ranks:
                candidates.append((min(ranks), file))
        if not candidates:
            raise SystemExit(f"No compatible wheel: {name}")
        file = min(candidates, key=lambda item: item[0])[1]
        lines.append(f"{name}=={version} --hash=sha256:{file['digests']['sha256']}")
    target = ROOT / "config/ui-requirements.lock"
    original = target.read_text(encoding="utf-8")
    names = {line.split("==")[0] for line in original.splitlines() if "==" in line}
    if names.intersection(PINS):
        raise SystemExit("Emotion pins already present; review an explicit dependency update.")
    target.write_text(original.rstrip() + "\n\n# Offline CPU emotion inference\n" + "\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
