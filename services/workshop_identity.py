"""Private publisher credentials and local upload receipts, scoped to a server."""
import hashlib
import secrets
from pathlib import Path

from models.schemas import AppError
from services.asset_service import atomic_json, checked, read_json
from services.storage_lock import metadata_lock


def server_key(base_url):
    return hashlib.sha256(base_url.rstrip('/').lower().encode()).hexdigest()


def publisher_key(root, base_url):
    path = checked(Path(root) / 'data/private/workshop-publishers.json', Path(root), areas=('private',))
    with metadata_lock():
        values = read_json(path, {})
        server = server_key(base_url)
        if server not in values:
            values[server] = secrets.token_hex(32)
            atomic_json(path, values)
        key = values[server]
        if not isinstance(key, str) or len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
            raise AppError('PUBLISHER_IDENTITY_INVALID', '上传者凭据损坏，请从私人备份恢复。')
        return key


def upload_receipts(root, base_url):
    path = checked(Path(root) / 'data/index/workshop-uploads.json', Path(root), areas=('index',))
    return read_json(path, {}).get(server_key(base_url), {})


def remember_upload(root, base_url, record, voice_id):
    path = checked(Path(root) / 'data/index/workshop-uploads.json', Path(root), areas=('index',))
    with metadata_lock():
        values = read_json(path, {})
        values.setdefault(server_key(base_url), {})[record['id']] = {
            'package_sha256': record['package_sha256'], 'local_voice_id': voice_id}
        atomic_json(path, values)
