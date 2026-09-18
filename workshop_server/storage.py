"""Bounded static ZIP validation shared with the desktop. Never loads checkpoints."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import wave
import zipfile

from workshop_server.schemas import MAX_PACKAGE_BYTES, Manifest

CHUNK = 1024 * 1024
MAX_MANIFEST = 64 * 1024


class PackageError(Exception):
    def __init__(self, code="PACKAGE_INVALID", message="音色包损坏、格式不支持或完整性校验失败。"):
        super().__init__(message)
        self.code, self.message = code, message


def sha256_file(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def size_limit(value):
    if type(value) is not int or not 1 <= value <= MAX_PACKAGE_BYTES:
        raise PackageError("PACKAGE_LIMIT_INVALID", "音色包大小上限必须在 1 字节至 1 GiB 之间。")
    return value


def _json_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def inspect_package(path, *, max_bytes=MAX_PACKAGE_BYTES):
    limit = size_limit(max_bytes)
    path = Path(path)
    try:
        if not 0 < path.stat().st_size <= limit:
            raise PackageError("PACKAGE_TOO_LARGE", "音色包为空或超过允许大小。")
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if not 4 <= len(members) <= 6 or len({i.filename for i in members}) != len(members):
                raise ValueError("entry count or duplicates")
            allowed = {"manifest.json", "weights/gpt.ckpt", "weights/sovits.pth",
                       "references/neutral.wav", "references/happy.wav", "references/sad.wav"}
            if any(i.filename not in allowed or i.orig_filename != i.filename for i in members):
                raise ValueError("path whitelist")
            if sum(i.file_size for i in members) > limit:
                raise PackageError("PACKAGE_TOO_LARGE", "音色包解压后的大小超过上限。")
            for item in members:
                mode = item.external_attr >> 16
                if (item.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                        or item.flag_bits & 1 or item.external_attr & 0x410
                        or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                        or not 0 < item.file_size <= limit):
                    raise ValueError("entry type or size")
            info = archive.getinfo("manifest.json")
            if info.file_size > MAX_MANIFEST:
                raise ValueError("manifest too large")
            raw = json.loads(archive.read(info), object_pairs_hook=_json_no_duplicates)
            manifest = Manifest.model_validate(raw)
            if set(archive.namelist()) != {"manifest.json", *(f.path for f in manifest.files)}:
                raise ValueError("unlisted file")
            for file in manifest.files:
                if archive.getinfo(file.path).file_size != file.bytes:
                    raise ValueError("file size")
                digest, count = hashlib.sha256(), 0
                with archive.open(file.path) as stream:
                    for chunk in iter(lambda: stream.read(CHUNK), b""):
                        count += len(chunk)
                        if count > file.bytes:
                            raise ValueError("expanded size")
                        digest.update(chunk)
                if count != file.bytes or digest.hexdigest() != file.sha256:
                    raise ValueError("file hash")
                if file.role == "reference":
                    # Full WAV payload check also on the server; no codec/model dependencies.
                    with archive.open(file.path) as stream, wave.open(stream, "rb") as wav:
                        channels, width, rate, frames = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
                        if min(channels, width, rate, frames) <= 0:
                            raise ValueError("empty WAV")
                        remaining = frames
                        while remaining:
                            n = min(remaining, 65536)
                            if len(wav.readframes(n)) != n * channels * width:
                                raise ValueError("truncated WAV")
                            remaining -= n
        return {"manifest": manifest.model_dump(mode="json"), "package_sha256": sha256_file(path),
                "package_bytes": path.stat().st_size}
    except PackageError:
        raise
    except (OSError, ValueError, KeyError, TypeError, EOFError, wave.Error, zipfile.BadZipFile, RuntimeError) as exc:
        raise PackageError() from exc


async def receive_package(request, target, *, max_bytes=MAX_PACKAGE_BYTES):
    """Parse multipart while receiving; do not spool an unbounded UploadFile first."""
    from python_multipart import MultipartParser
    from python_multipart.multipart import parse_options_header
    limit = size_limit(max_bytes)
    media_type, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary", b"")
    if media_type != b"multipart/form-data" or not 1 <= len(boundary) <= 200:
        raise PackageError(message="请上传 multipart/form-data 格式的 .rvoice 文件。")
    state = dict(parts=0, bytes=0, ended=False, headers={}, field=bytearray(), value=bytearray(), header_bytes=0)
    with Path(target).open("xb") as output:
        def begin():
            state["parts"] += 1
            if state["parts"] != 1:
                raise PackageError(message="每次只能上传一个音色包。")
        def header_field(data, start, end):
            state["header_bytes"] += end-start
            if state["header_bytes"] > MAX_MANIFEST:
                raise PackageError()
            state["field"].extend(data[start:end])
        def header_value(data, start, end):
            state["header_bytes"] += end-start
            if state["header_bytes"] > MAX_MANIFEST:
                raise PackageError()
            state["value"].extend(data[start:end])
        def header_end():
            state["headers"][bytes(state["field"]).lower()] = bytes(state["value"])
            state["field"].clear()
            state["value"].clear()
        def headers_finished():
            kind, parameters = parse_options_header(state["headers"].get(b"content-disposition", b""))
            if (kind != b"form-data" or parameters.get(b"name") != b"file"
                    or not parameters.get(b"filename", b"").lower().endswith(b".rvoice")):
                raise PackageError(message="上传字段必须为 file，文件扩展名须为 .rvoice。")
        def data(data, start, end):
            state["bytes"] += end-start
            if state["bytes"] > limit:
                raise PackageError("PACKAGE_TOO_LARGE", "音色包超过上传大小上限。")
            output.write(memoryview(data)[start:end])
        def ended():
            state["ended"] = True
        parser = MultipartParser(boundary, {"on_part_begin": begin, "on_header_field": header_field,
            "on_header_value": header_value, "on_header_end": header_end, "on_headers_finished": headers_finished,
            "on_part_data": data, "on_end": ended})
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > limit + MAX_MANIFEST:
                raise PackageError("PACKAGE_TOO_LARGE", "上传请求超过大小上限。")
            parser.write(chunk)
        parser.finalize()
        if state["parts"] != 1 or not state["ended"] or not state["bytes"]:
            raise PackageError(message="音色包上传未完成，请重试。")
        output.flush()
        os.fsync(output.fileno())
