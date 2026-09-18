"""Optional synchronous HTTP client. Failures never become application startup failures."""
from __future__ import annotations

import hashlib
import json
import os
import io
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from models.schemas import AppError
from services.asset_service import checked
from services.project_paths import PROJECT_ROOT
from services.voice_package_service import inspect_voice_package
from workshop_server.storage import CHUNK, size_limit
from workshop_server.covers import MAX_COVER_BYTES, normalize_cover
from services.workshop_identity import publisher_key, upload_receipts, remember_upload


def load_config(*, root=PROJECT_ROOT):
    defaults = dict(base_url="http://127.0.0.1:8090", auto_start_local=False, connect_timeout_seconds=5,
                    read_timeout_seconds=1800, max_package_bytes=1073741824)
    try:
        path = Path(root) / "config/workshop.local.json"
        if path.exists():
            defaults.update(json.loads(path.read_text(encoding="utf-8")))
        url = urlsplit(defaults["base_url"])
        if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in ("", "/")):
            raise ValueError("invalid server address")
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError("invalid port")
        if type(defaults.get("auto_start_local", True)) is not bool:
            raise ValueError("invalid local startup option")
        for key in ("connect_timeout_seconds", "read_timeout_seconds"):
            if not 0 < defaults[key] <= 3600:
                raise ValueError("invalid timeout")
        size_limit(defaults["max_package_bytes"])
        return defaults
    except Exception as exc:
        raise AppError("WORKSHOP_CONFIG_INVALID", "工坊连接配置无效，请检查本地配置。") from exc


class WorkshopClient:
    def __init__(self, *, config=None, root=PROJECT_ROOT, transport=None):
        self.root = Path(root).resolve()
        self.config = config or load_config(root=self.root)
        self.transport = transport

    def _client(self):
        if self.transport is None:
            from services.workshop_runtime import ensure_local_service
            ensure_local_service(self.config, self.root)
        return httpx.Client(base_url=self.config["base_url"], follow_redirects=False, trust_env=False,
            timeout=httpx.Timeout(self.config["read_timeout_seconds"], connect=self.config["connect_timeout_seconds"]),
            transport=self.transport)

    def _check(self, response):
        if response.status_code >= 300:
            messages = {403: ("UPLOAD_UNAUTHORIZED", "上传令牌无效或服务端未开放上传。"),
                        409: ("PACKAGE_DUPLICATE", "该音色包已经上传。"),
                        404: ("VOICE_NOT_FOUND", "所选工坊音色已不存在。"),
                        413: ("PACKAGE_TOO_LARGE", "音色包超过服务允许的大小。")}
            code, message = messages.get(response.status_code, ("WORKSHOP_REQUEST_FAILED", "工坊操作失败，请检查服务状态后重试。"))
            # Never reflect remote error bodies, request headers or tokens into UI/logs.
            raise AppError(code, message)

    def _publisher_headers(self):
        return {'X-Publisher-Key': publisher_key(self.root, self.config['base_url'])}

    def _json(self, route, params=None, headers=None):
        try:
            with self._client() as client, client.stream("GET", route, params=params, headers=headers) as response:
                self._check(response)
                content = bytearray()
                for chunk in response.iter_bytes(CHUNK):
                    content.extend(chunk)
                    if len(content) > 2 * CHUNK:
                        raise ValueError("metadata too large")
                return json.loads(content)
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise AppError("WORKSHOP_UNAVAILABLE", "无法连接工坊或服务响应无效；本地功能仍可使用。") from exc

    def health(self):
        value = self._json("/health")
        if not isinstance(value, dict) or value.get("status") != "ok" or value.get("api_version") != "1":
            raise AppError("WORKSHOP_INCOMPATIBLE", "工坊 API 版本不兼容。")
        return value

    def list_voices(self, query="", limit=50, offset=0):
        if not 1 <= limit <= 100 or offset < 0 or len(query) > 200:
            raise AppError("REQUEST_INVALID", "搜索或分页参数无效。")
        value = self._json("/api/v1/voices", dict(q=query, limit=limit, offset=offset), self._publisher_headers())
        if not isinstance(value, list) or len(value) > limit:
            raise AppError("WORKSHOP_RESPONSE_INVALID", "工坊列表格式无效。")
        try:
            for row in value:
                UUID(row["id"])
                size_limit(row["package_bytes"])
                if len(row["package_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in row["package_sha256"]):
                    raise ValueError("hash")
                for key in ("display_name", "author", "description", "license_name", "created_at"):
                    if not isinstance(row[key], str) or len(row[key]) > 2000:
                        raise ValueError("metadata")
                if not isinstance(row["emotions"], list) or any(e not in ("neutral", "happy", "sad") for e in row["emotions"]):
                    raise ValueError("emotions")
        except (KeyError, ValueError, TypeError) as exc:
            raise AppError("WORKSHOP_RESPONSE_INVALID", "工坊列表字段无效。") from exc
        receipts = upload_receipts(self.root, self.config['base_url'])
        for row in value:
            row.pop('local_voice_id', None)  # Never trust a server-supplied local ID.
            row['can_edit_cover'] = row.get('can_edit_cover') is True
            row['can_withdraw'] = row.get('can_withdraw') is True
            receipt = receipts.get(row['id'], {})
            if receipt.get('package_sha256') == row['package_sha256']:
                row['local_voice_id'] = receipt.get('local_voice_id')
        return value

    def upload_voice(self, package_path, upload_token="", *, local_voice_id=None):
        inspection = inspect_voice_package(package_path, max_bytes=self.config["max_package_bytes"])
        token = self._upload_token(upload_token)
        if not token:
            raise AppError("UPLOAD_TOKEN_REQUIRED", "请填写上传令牌。")
        try:
            with self._client() as client, Path(package_path).open("rb") as source:
                with client.stream("POST", "/api/v1/voices", headers={"X-Upload-Token": token, **self._publisher_headers()},
                                   files={"file": ("voice.rvoice", source, "application/octet-stream")}) as response:
                    self._check(response)
                    content = bytearray()
                    for chunk in response.iter_bytes(CHUNK):
                        content.extend(chunk)
                        if len(content) > CHUNK:
                            raise ValueError("metadata too large")
                    value = json.loads(content)
                    UUID(value["id"])
                    if value.get('package_sha256') != inspection['package_sha256']:
                        raise ValueError('upload hash mismatch')
                    if local_voice_id:
                        remember_upload(self.root, self.config['base_url'], value, local_voice_id)
                    return value
        except (httpx.HTTPError, ValueError, OSError, KeyError, TypeError) as exc:
            raise AppError("WORKSHOP_UPLOAD_FAILED", "上传失败或连接中断，请刷新列表确认后重试。") from exc

    def _upload_token(self, supplied=""):
        token = supplied or self.config.get("upload_token", "")
        if not token and self.transport is None:
            from services.workshop_runtime import ensure_local_service
            token = ensure_local_service(self.config, self.root)
        return token

    def withdraw_voice(self, workshop_id):
        try:
            UUID(workshop_id)
            with self._client() as client, client.stream("DELETE", f"/api/v1/voices/{workshop_id}",
                    headers=self._publisher_headers()) as response:
                if response.status_code == 403:
                    raise AppError('WITHDRAW_FORBIDDEN', '仅上传者可以下架此音色；当前平台没有对应上传者凭据。')
                self._check(response)
                body = bytearray()
                for chunk in response.iter_bytes(65536):
                    body.extend(chunk)
                    if len(body) > 65536:
                        raise ValueError('response size')
                value = json.loads(body)
                if value.get('id') != workshop_id or value.get('withdrawn') is not True:
                    raise ValueError('withdraw response')
                return value
        except (httpx.HTTPError, ValueError, OSError, TypeError, AttributeError) as exc:
            raise AppError('WORKSHOP_WITHDRAW_FAILED', '下架结果未确认，请刷新列表后重试；本地音色不受影响。') from exc

    def set_cover(self, workshop_id, path, token=""):
        from workshop_server.storage import PackageError
        try:
            UUID(workshop_id)
            with Path(path).open("rb") as handle:
                png = normalize_cover(handle.read(MAX_COVER_BYTES + 1))
            with self._client() as client, client.stream("POST", f"/api/v1/voices/{workshop_id}/cover", content=png,
                    headers={**self._publisher_headers(), "Content-Type": "image/png"}) as response:
                if response.status_code == 403:
                    raise AppError('COVER_FORBIDDEN', '仅上传者可以修改此音色的封面；当前平台没有对应上传者凭据。')
                self._check(response)
                body = bytearray()
                for chunk in response.iter_bytes(65536):
                    body.extend(chunk)
                    if len(body) > 65536:
                        raise ValueError("cover response size")
                digest = json.loads(body).get("cover_sha256")
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise ValueError("cover response hash")
                return digest
        except PackageError as exc:
            raise AppError(exc.code, exc.message) from exc
        except (httpx.HTTPError, ValueError, OSError, TypeError) as exc:
            raise AppError("COVER_SAVE_FAILED", "封面保存失败，请检查图片和服务连接。") from exc

    def cover_image(self, record):
        """Use validated content hashes as cache keys, never remote filenames."""
        from PIL import Image
        from workshop_server.storage import PackageError
        digest = record.get("cover_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            return None
        cache = checked(self.root / "data/cache/workshop-covers" / (digest + ".png"), self.root, areas=("cache",))
        try:
            if cache.exists():
                data = cache.read_bytes() if cache.stat().st_size <= MAX_COVER_BYTES else b""
            else:
                data = bytearray()
                with self._client() as client, client.stream("GET", f'/api/v1/voices/{UUID(record["id"])}/cover', timeout=5) as response:
                    self._check(response)
                    for chunk in response.iter_bytes(65536):
                        data.extend(chunk)
                        if len(data) > MAX_COVER_BYTES:
                            raise ValueError("cover size")
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("cover hash")
            png = normalize_cover(data)
            if not cache.exists():
                cache.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache.with_name(uuid4().hex + ".tmp")
                try:
                    temporary.write_bytes(data)
                    os.replace(temporary, cache)
                finally:
                    temporary.unlink(missing_ok=True)
            with Image.open(io.BytesIO(png)) as image:
                return image.copy()
        except (AppError, PackageError, httpx.HTTPError, OSError, ValueError, KeyError):
            return None  # A broken optional cover never hides a downloadable voice.

    def download_voice(self, workshop_id, target_path=None, expected_size=None, *, expected_sha256=None):
        try:
            UUID(workshop_id)
        except (ValueError, TypeError) as exc:
            raise AppError("WORKSHOP_ID_INVALID", "请选择有效的工坊音色。") from exc
        directory = checked(self.root / "data/tmp/workshop-downloads", self.root, areas=("tmp",))
        directory.mkdir(parents=True, exist_ok=True)
        partial = directory / (uuid4().hex + ".part")
        target = Path(target_path) if target_path else partial.with_suffix(".rvoice")
        target = checked(target, self.root, areas=("tmp/workshop-downloads",))
        if target.suffix != ".rvoice" or target.exists():
            raise AppError("DOWNLOAD_TARGET_INVALID", "下载目标必须为新的临时音色包。")
        try:
            with self._client() as client, client.stream("GET", f"/api/v1/voices/{workshop_id}/download",
                                                         headers={"Accept-Encoding": "identity"}) as response:
                self._check(response)
                length = int(response.headers["Content-Length"])
                digest = expected_sha256 or response.headers.get("X-Package-SHA256")
                if (not 0 < length <= self.config["max_package_bytes"] or not digest
                        or expected_size is not None and length != expected_size):
                    raise ValueError("download metadata")
                count, actual = 0, hashlib.sha256()
                with partial.open("xb") as output:
                    for chunk in response.iter_bytes(CHUNK):
                        count += len(chunk)
                        if count > length:
                            raise ValueError("download exceeded limit")
                        actual.update(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if count != length or actual.hexdigest() != digest:
                    raise ValueError("download hash or size")
            # rename never overwrites an existing destination on Windows.
            partial.rename(target)
            return target
        except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
            raise AppError("WORKSHOP_DOWNLOAD_FAILED", "下载中断或大小、哈希校验失败，请重试。") from exc
        finally:
            partial.unlink(missing_ok=True)


def health():
    return WorkshopClient().health()


def list_voices(query="", limit=50, offset=0):
    return WorkshopClient().list_voices(query, limit, offset)


def upload_voice(package_path, upload_token):
    return WorkshopClient().upload_voice(package_path, upload_token)


def download_voice(workshop_id, target_path, expected_size=None):
    return WorkshopClient().download_voice(workshop_id, target_path, expected_size)
