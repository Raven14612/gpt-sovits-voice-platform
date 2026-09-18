"""Small constructed packages. These are not synthesis-capable voice models."""
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4
import wave
import zipfile


def make_package(path, *, transform=None, extra=None, weight_bytes=64):
    audio = io.BytesIO()
    with wave.open(audio, "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 160)
    files = {"weights/gpt.ckpt": b"\0" * weight_bytes, "weights/sovits.pth": b"\1" * weight_bytes,
             "references/neutral.wav": audio.getvalue()}
    manifest = dict(schema_version=1, package_id=str(uuid4()), created_at="2026-09-15T00:00:00+00:00",
        client_min_version="2.0", engine=dict(family="GPT-SoVITS", model_version="v2Pro"),
        voice=dict(display_name="临时测试音色", author="测试作者", description="仅用于临时目录结构测试", emotions=["neutral"],
                   references=[dict(emotion="neutral", path="references/neutral.wav", prompt_text="测试参考文本", language="zh")]),
        license=dict(name="CC BY 4.0", rights_confirmed=True),
        files=[dict(role="reference" if name.endswith("wav") else "gpt_weight" if name.endswith("ckpt") else "sovits_weight",
                    path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()) for name, data in files.items()])
    if transform:
        transform(manifest, files)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for name, data in files.items():
            archive.writestr(name, data)
        if extra:
            archive.writestr(extra, b"forbidden")
    return Path(path)
