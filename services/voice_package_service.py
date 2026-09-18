from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4
import zipfile

from models.schemas import AppError, EmotionReference, VoiceProfile, utc_now
from services import voice_service
from services.asset_service import atomic_json, checked, checked_tree
from services.engine_service import load_engine_config
from services.process_control import run_owned_command
from services.project_paths import PROJECT_ROOT, project_environment
from services.storage_lock import metadata_lock
from services.wav_service import inspect_wav
from workshop_server.schemas import LICENSES, Manifest, MAX_PACKAGE_BYTES
from workshop_server.storage import CHUNK, PackageError, inspect_package, sha256_file


def inspect_voice_package(package_path, *, max_bytes=MAX_PACKAGE_BYTES):
    try:
        return inspect_package(package_path, max_bytes=max_bytes)
    except PackageError as exc:
        raise AppError(exc.code, exc.message) from exc


def export_voice_package(voice_id, author, description, license_name, rights_confirmed):
    directory = checked(PROJECT_ROOT / "data/tmp/voice-packages", PROJECT_ROOT, areas=("tmp",))
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="export-", dir=directory) as temporary:
        return _export_voice_package(voice_id, author, description, license_name, rights_confirmed, Path(temporary))


def _export_voice_package(voice_id, author, description, license_name, rights_confirmed, work):
    if rights_confirmed is not True:
        raise AppError("RIGHTS_REQUIRED", "请先确认拥有分享音色及参考音频的权利。")
    if (license_name not in LICENSES or not isinstance(author, str) or not 1 <= len(author.strip()) <= 80
            or not isinstance(description, str) or not 1 <= len(description.strip()) <= 2000):
        raise AppError("PACKAGE_METADATA_INVALID", "作者须为 1–80 字，简介须为 1–2000 字，并选择支持的许可。")
    with metadata_lock():
        profile = voice_service.get_voice(voice_id, voice_service.VOICE_INDEX)
        if not profile or profile.status != "verified" or not profile.references:
            raise AppError("VOICE_STATE_INVALID", "只能分享有参考音频的可用音色。")
        files = []
        for role, source, name in (("gpt_weight", profile.gpt_weight, "weights/gpt.ckpt"),
                                  ("sovits_weight", profile.sovits_weight, "weights/sovits.pth")):
            if source is None:
                raise AppError("VOICE_WEIGHTS_MISSING", "音色权重缺失。")
            source = checked(source, PROJECT_ROOT, areas=("voices", "training"))
            if not source.is_file() or source.stat().st_size <= 0:
                raise AppError("VOICE_WEIGHTS_MISSING", "音色权重缺失或为空。")
            files.append((role, source, name))
        # Remove training paths before sharing; the user's archived weights stay intact.
        clean = work / "sanitized"
        _sanitize(files[0][1], files[1][1], clean)
        files = [(role, clean / Path(name).name, name) for role, _, name in files]
        references = []
        for ref in profile.references:
            source = checked(ref.audio_path, PROJECT_ROOT, areas=("datasets", "voices"))
            inspect_wav(source)
            name = f"references/{ref.emotion}.wav"
            files.append(("reference", source, name))
            references.append(dict(emotion=ref.emotion, path=name, prompt_text=ref.prompt_text, language=ref.language))
        manifest = Manifest.model_validate(dict(schema_version=1, package_id=str(uuid4()), created_at=utc_now(),
            client_min_version="2.0", engine=dict(family="GPT-SoVITS", model_version="v2Pro"),
            voice=dict(display_name=profile.display_name, author=author.strip(), description=description.strip(),
                       emotions=[ref.emotion for ref in profile.references], references=references),
            license=dict(name=license_name, rights_confirmed=True),
            files=[dict(role=role, path=name, bytes=source.stat().st_size, sha256=sha256_file(source))
                   for role, source, name in files]))
        directory = checked(PROJECT_ROOT / "data/tmp/voice-packages", PROJECT_ROOT, areas=("tmp",))
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (uuid4().hex + ".rvoice")
        try:
            with target.open("xb") as stream:
                with zipfile.ZipFile(stream, "w", zipfile.ZIP_STORED) as archive:
                    archive.writestr("manifest.json", manifest.model_dump_json())
                    for _, source, name in files:
                        with source.open("rb") as incoming, archive.open(name, "w", force_zip64=True) as outgoing:
                            shutil.copyfileobj(incoming, outgoing, CHUNK)
                stream.flush()
                os.fsync(stream.fileno())
            inspect_voice_package(target)
            return target
        except Exception:
            target.unlink(missing_ok=True)
            raise


def _sanitize(gpt, sovits, output):
    try:
        config = load_engine_config()
        environment = project_environment(root=PROJECT_ROOT, python=config.python_path, engine_root=config.engine_root)
        environment["CUDA_VISIBLE_DEVICES"] = ""
        result = run_owned_command([str(config.python_path), str(PROJECT_ROOT / "scripts/sanitize_voice_checkpoint.py"),
            "--gpt", str(gpt), "--sovits", str(sovits), "--output", str(output)],
            timeout=300, capture_output=True, cwd=PROJECT_ROOT, env=environment)
        if result.returncode or any(not (output / name).is_file() for name in ("gpt.ckpt", "sovits.pth")):
            raise ValueError("unsafe checkpoint")
    except Exception as exc:
        raise AppError("CHECKPOINT_UNSAFE", "模型权重未通过 CPU 安全预检或模型运行时不可用，已停止处理此音色包。") from exc


def install_voice_package(package_path, *, origin_workshop_id=None):
    directory = checked(PROJECT_ROOT / "data/tmp/voice-packages", PROJECT_ROOT, areas=("tmp",))
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="install-", dir=directory) as temporary:
        work = Path(temporary)
        # Validate an owned snapshot; an external file cannot change between inspection/extraction.
        incoming = work / "source.rvoice"
        with Path(package_path).open("rb") as src, incoming.open("xb") as dst:
            total = 0
            for chunk in iter(lambda: src.read(CHUNK), b""):
                total += len(chunk)
                if total > MAX_PACKAGE_BYTES:
                    raise AppError("PACKAGE_TOO_LARGE", "音色包超过 1 GiB。")
                dst.write(chunk)
        inspection = inspect_voice_package(incoming)
        manifest = inspection["manifest"]
        package_hash = inspection["package_sha256"]
        with metadata_lock():
            _check_duplicate(package_hash)
        extracted = work / "originals"
        with zipfile.ZipFile(incoming) as archive:
            for file in manifest["files"]:
                target = extracted / file["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(file["path"]) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst, CHUNK)
        clean = work / "sanitized"
        _sanitize(extracted / "weights/gpt.ckpt", extracted / "weights/sovits.pth", clean)
        voice_id = "voice-" + uuid4().hex
        target = checked(PROJECT_ROOT / "data/voices" / voice_id, PROJECT_ROOT, areas=("voices",))
        stage = work / "voice"
        (stage / "weights").mkdir(parents=True)
        (stage / "references").mkdir()
        for name in ("gpt.ckpt", "sovits.pth"):
            shutil.move(str(clean / name), str(stage / "weights" / name))
        refs = []
        for ref in manifest["voice"]["references"]:
            shutil.copyfile(extracted / ref["path"], stage / ref["path"])
            inspect_wav(stage / ref["path"])
            refs.append(EmotionReference(emotion=ref["emotion"], audio_path=target / ref["path"],
                                         prompt_text=ref["prompt_text"], language="zh"))
        profile = VoiceProfile(voice_id=voice_id, display_name=manifest["voice"]["display_name"],
            feature_name=manifest["voice"]["display_name"], dataset_id="", engine_profile="verified-v2pro", status="verified",
            origin_type="workshop", origin_workshop_id=origin_workshop_id, package_hash=package_hash,
            gpt_weight=target / "weights/gpt.ckpt", sovits_weight=target / "weights/sovits.pth", references=refs,
            weight_hashes={"gpt": sha256_file(stage / "weights/gpt.ckpt"), "sovits": sha256_file(stage / "weights/sovits.pth")})
        atomic_json(stage / "package-manifest.json", manifest)
        atomic_json(stage / "ownership.json", {"voice_id": voice_id, "origin_type": "workshop"})
        with metadata_lock():
            _check_duplicate(package_hash)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage, target)
            try:
                # Strict read preserves a corrupt or concurrently changed V1 index.
                records = voice_service._read_voice_data(voice_service.VOICE_INDEX) if voice_service.VOICE_INDEX.exists() else []
                records.append(voice_service._stored_profile(profile))
                voice_service._write_voice_data(voice_service.VOICE_INDEX, records)
            except Exception:
                checked_tree(target, PROJECT_ROOT, areas=("voices",))
                shutil.rmtree(target)
                raise
        return profile


def _check_duplicate(package_hash):
    index = voice_service.VOICE_INDEX
    records = voice_service._read_voice_data(index) if index.exists() else []
    if any(row.get("package_hash") == package_hash for row in records):
        raise AppError("PACKAGE_ALREADY_INSTALLED", "该音色包已安装；若在回收站中，请先恢复。")
