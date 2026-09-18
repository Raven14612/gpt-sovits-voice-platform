from __future__ import annotations

from datetime import datetime, timezone
import hmac
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi import FastAPI, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect

from workshop_server.database import Database
from workshop_server.schemas import MAX_PACKAGE_BYTES
from workshop_server.storage import CHUNK, PackageError, inspect_package, receive_package, size_limit
from workshop_server.covers import MAX_COVER_BYTES, normalize_cover


def error(code, message, status):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def publisher_hash(request):
    key = request.headers.get('X-Publisher-Key', '')
    if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
        return None
    return hashlib.sha256(key.encode()).hexdigest()


def create_app(*, data_dir=None, upload_token=None, max_package_bytes=MAX_PACKAGE_BYTES):
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    root = Path(data_dir or os.environ.get("WORKSHOP_DATA_DIR", "workshop_data")).resolve()
    for name in ("packages", "tmp", "covers"):
        (root / name).mkdir(parents=True, exist_ok=True)
    database = Database(root)
    token = os.environ.get("WORKSHOP_UPLOAD_TOKEN", "") if upload_token is None else upload_token
    limit = size_limit(max_package_bytes)
    application.state.database = database

    @application.exception_handler(PackageError)
    async def package_error(request, exc):
        return error(exc.code, exc.message, 413 if exc.code == "PACKAGE_TOO_LARGE" else 400)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error("REQUEST_INVALID", "请求参数无效。", 422)

    @application.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error("NOT_FOUND" if exc.status_code == 404 else "REQUEST_INVALID", "请求资源不存在或方法不支持。", exc.status_code)

    @application.exception_handler(Exception)
    async def internal_error(request, exc):
        return error("SERVER_ERROR", "服务暂时无法完成操作，请稍后重试。", 500)

    @application.get("/health")
    def health():
        return {"status": "ok", "api_version": "1"}

    @application.get("/api/v1/voices")
    def voices(request: Request, q: str = Query("", max_length=200), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        return JSONResponse(database.list(q, limit, offset, publisher_hash(request)), headers={'Cache-Control': 'no-store'})

    @application.post("/api/v1/voices")
    async def upload(request: Request):
        supplied = request.headers.get("X-Upload-Token", "")
        if not token or not hmac.compare_digest(supplied.encode(), token.encode()):
            return error("UPLOAD_UNAUTHORIZED", "上传令牌无效或服务端未开放上传。", 403)
        owner = publisher_hash(request)
        if owner is None:
            return error('PUBLISHER_REQUIRED', '请更新客户端以提供上传者凭据。', 403)
        temporary = root / "tmp" / (uuid4().hex + ".upload")
        target = None
        committed = False
        try:
            await receive_package(request, temporary, max_bytes=limit)
            info = await run_in_threadpool(inspect_package, temporary, max_bytes=limit)
            manifest = info["manifest"]
            voice_id = str(uuid4())
            relative = "packages/" + voice_id + ".rvoice"
            target = root / relative
            os.replace(temporary, target)
            row = dict(id=voice_id, display_name=manifest["voice"]["display_name"], author=manifest["voice"]["author"],
                description=manifest["voice"]["description"], license_name=manifest["license"]["name"],
                engine_family=manifest["engine"]["family"], model_version=manifest["engine"]["model_version"],
                emotions_json=json.dumps(manifest["voice"]["emotions"]), package_path=relative,
                package_sha256=info["package_sha256"], package_bytes=info["package_bytes"],
                created_at=datetime.now(timezone.utc).isoformat(), owner_key_hash=owner)
            result = await run_in_threadpool(database.insert, row)
            committed = True
            return JSONResponse(result, status_code=201)
        except sqlite3.IntegrityError:
            return error("PACKAGE_DUPLICATE", "该音色包已经上传。", 409)
        except ClientDisconnect:
            return error("UPLOAD_INTERRUPTED", "上传已中断，请重试。", 400)
        except (OSError, sqlite3.Error):
            return error("STORAGE_UNAVAILABLE", "存储空间不足或服务存储不可用，请联系管理员。", 503)
        finally:
            temporary.unlink(missing_ok=True)
            if target and not committed:
                target.unlink(missing_ok=True)

    @application.delete("/api/v1/voices/{voice_id}")
    def withdraw(voice_id: str, request: Request):
        if database.get(voice_id) is None:
            return error("VOICE_NOT_FOUND", "音色不存在。", 404)
        owner = publisher_hash(request)
        if not owner or not database.withdraw(voice_id, owner, datetime.now(timezone.utc).isoformat()):
            return error("WITHDRAW_FORBIDDEN", "仅上传者可以下架此音色。", 403)
        return {"id": voice_id, "withdrawn": True}

    @application.get("/api/v1/voices/{voice_id}/download")
    def download(voice_id: str):
        row = database.get(voice_id)
        if row is None or row.get('withdrawn_at'):
            return error("VOICE_NOT_FOUND", "音色包不存在。", 404)
        path = (root / row["package_path"]).resolve()
        if not path.is_relative_to(root / "packages") or not path.is_file():
            return error("VOICE_NOT_FOUND", "音色包不存在。", 404)
        # Open before sending headers, so a missing/unreadable file cannot count as a download.
        try:
            handle = path.open("rb")
        except OSError:
            return error("VOICE_NOT_FOUND", "音色包暂时无法读取。", 404)
        def chunks():
            try:
                database.downloaded(voice_id)
                for block in iter(lambda: handle.read(CHUNK), b""):
                    yield block
            finally:
                handle.close()
        return StreamingResponse(chunks(), media_type="application/octet-stream", headers={
            "Content-Length": str(os.fstat(handle.fileno()).st_size),
            "Content-Disposition": f'attachment; filename="{row["id"]}.rvoice"',
            "X-Package-SHA256": row["package_sha256"]})

    @application.post("/api/v1/voices/{voice_id}/cover")
    async def set_cover(voice_id: str, request: Request):
        row = database.get(voice_id)
        if row is None or row.get('withdrawn_at'):
            return error("VOICE_NOT_FOUND", "音色不存在。", 404)
        owner = publisher_hash(request)
        if not owner or not row.get('owner_key_hash') or not hmac.compare_digest(owner, row['owner_key_hash']):
            return error('COVER_FORBIDDEN', '仅上传者可以修改此音色的封面。', 403)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_COVER_BYTES:
                return error("COVER_TOO_LARGE", "封面不能超过 4 MiB。", 413)
        png = await run_in_threadpool(normalize_cover, data)
        digest = hashlib.sha256(png).hexdigest()
        temporary = root / "tmp" / (uuid4().hex + ".png")
        try:
            with temporary.open("xb") as handle:
                handle.write(png)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, root / "covers" / (digest + ".png"))
            if not database.set_cover(voice_id, digest, owner):
                return error("VOICE_NOT_FOUND", "音色已下架或归属已变更。", 404)
            return {"cover_sha256": digest}
        finally:
            temporary.unlink(missing_ok=True)

    @application.get("/api/v1/voices/{voice_id}/cover")
    def get_cover(voice_id: str):
        row = database.get(voice_id)
        digest = row.get("cover_sha256") if row and not row.get('withdrawn_at') else None
        if not digest or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            return error("COVER_NOT_FOUND", "暂无封面。", 404)
        path = root / "covers" / (digest + ".png")
        if not path.is_file():
            return error("COVER_NOT_FOUND", "暂无封面。", 404)
        return FileResponse(path, media_type="image/png", headers={"ETag": digest, "Cache-Control": "no-store"})

    return application


# Uvicorn --factory avoids initializing storage when imported by the desktop/tests.
