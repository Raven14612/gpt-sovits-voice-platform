import hashlib
import io
from PIL import Image
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from workshop_server.app import create_app
from workshop_server.tests.helpers import make_package


class WorkshopServerTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.package = make_package(self.root / "test.rvoice")
        self.data = self.root / "server"
        self.app = create_app(data_dir=self.data, upload_token="test-secret")
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def upload(self, path=None, token="test-secret", client=None):
        with (path or self.package).open("rb") as handle:
            return (client or self.client).post("/api/v1/voices", files={"file": ("test.rvoice", handle)},
                                               headers={"X-Upload-Token": token, 'X-Publisher-Key': 'a'*64})

    def test_upload_list_download_duplicate_restart(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        row = response.json()
        self.assertNotIn("package_path", row)
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(len(self.client.get("/api/v1/voices?q=作者").json()), 1)
        download = self.client.get(f'/api/v1/voices/{row["id"]}/download')
        self.assertEqual(hashlib.sha256(download.content).hexdigest(), row["package_sha256"])
        self.assertEqual(int(download.headers["content-length"]), len(download.content))
        with TestClient(create_app(data_dir=self.data, upload_token="test-secret")) as restarted:
            self.assertEqual(len(restarted.get("/api/v1/voices").json()), 1)
            self.assertEqual(restarted.get(f'/api/v1/voices/{row["id"]}/download').content, self.package.read_bytes())
        self.assertEqual(list((self.data / "tmp").iterdir()), [])

    def test_token_invalid_missing_and_bad_inputs(self):
        self.assertEqual(self.upload(token="wrong").status_code, 403)
        with TestClient(create_app(data_dir=self.root / "unconfigured", upload_token="")) as client:
            self.assertEqual(self.upload(client=client).status_code, 403)
        for i, kwargs in enumerate([dict(extra="../attack.py"), dict(extra="run.py"),
                dict(transform=lambda m, f: m["files"][0].update(sha256="a"*64))]):
            package = make_package(self.root / f"bad{i}.rvoice", **kwargs)
            self.assertEqual(self.upload(package).status_code, 400)
        self.assertEqual(list((self.data / "tmp").iterdir()), [])
        self.assertEqual(list((self.data / "packages").iterdir()), [])

    def test_limit_and_database_failure_cleanup(self):
        with TestClient(create_app(data_dir=self.root / "small", upload_token="test-secret", max_package_bytes=100)) as client:
            self.assertEqual(self.upload(client=client).status_code, 413)
        self.assertEqual(list((self.root / "small/tmp").iterdir()), [])
        with patch.object(self.app.state.database, "insert", side_effect=OSError("private server path")):
            response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private", response.text)
        self.assertEqual(list((self.data / "packages").iterdir()), [])
        self.assertEqual(list((self.data / "tmp").iterdir()), [])

    def test_missing_download_not_counted_and_validation_error_uniform(self):
        row = self.upload().json()
        package = self.data / self.app.state.database.get(row["id"])["package_path"]
        package.unlink()
        self.assertEqual(self.client.get(f'/api/v1/voices/{row["id"]}/download').status_code, 404)
        self.assertEqual(self.app.state.database.get(row["id"])["download_count"], 0)
        self.assertIn("error", self.client.get("/api/v1/voices?limit=101").json())
        self.assertNotIn(str(self.data), self.client.get("/health").text)

    def test_cover_validation_authentication_and_restart(self):
        row = self.upload().json()
        route = f'/api/v1/voices/{row["id"]}/cover'
        png = io.BytesIO()
        Image.new('RGB', (80, 80), 'red').save(png, format='PNG')
        headers = {'X-Publisher-Key': 'a'*64}
        self.assertEqual(self.client.post(route, content=png.getvalue()).status_code, 403)
        self.assertEqual(self.client.post(route, content=b'<svg/>', headers=headers).status_code, 400)
        self.assertEqual(self.client.post(route, content=b'x'*(4*1024*1024+1), headers=headers).status_code, 413)
        result = self.client.post(route, content=png.getvalue(), headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        digest = result.json()['cover_sha256']
        with TestClient(create_app(data_dir=self.data)) as restarted:
            self.assertEqual(restarted.post(route, content=png.getvalue(), headers=headers).status_code, 200)
            response = restarted.get(route)
            self.assertEqual(hashlib.sha256(response.content).hexdigest(), digest)
            self.assertEqual(restarted.get('/api/v1/voices').json()[0]['cover_sha256'], digest)
        self.assertEqual(list((self.data / 'tmp').iterdir()), [])

    def test_other_publisher_and_shared_upload_token_cannot_edit_cover(self):
        row = self.upload().json()
        route = f'/api/v1/voices/{row["id"]}/cover'
        for headers in ({'X-Upload-Token': 'test-secret'},
                        {'X-Upload-Token': 'test-secret', 'X-Publisher-Key': 'b'*64}):
            response = self.client.post(route, content=b'not read before authorization', headers=headers)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()['error']['code'], 'COVER_FORBIDDEN')
        for key, allowed in [('a'*64, True), ('b'*64, False), ('', False)]:
            result = self.client.get('/api/v1/voices', headers={'X-Publisher-Key': key}).json()[0]
            self.assertIs(result['can_edit_cover'], allowed)
            self.assertNotIn('owner_key_hash', result)
        self.assertNotIn('owner_key_hash', row)
        with self.app.state.database.connect() as db:
            db.execute('UPDATE voices SET owner_key_hash=NULL WHERE id=?', (row['id'],))
        self.assertEqual(self.client.post(route, content=b'', headers={'X-Publisher-Key':'a'*64}).status_code, 403)

    def test_upload_requires_publisher_identity(self):
        with self.package.open('rb') as handle:
            result = self.client.post('/api/v1/voices', files={'file': ('voice.rvoice', handle)},
                                      headers={'X-Upload-Token': 'test-secret'})
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.app.state.database.list(), [])

    def test_withdraw_permissions_persistence_and_local_copy(self):
        row = self.upload().json()
        route = f'/api/v1/voices/{row["id"]}'
        owner = {'X-Publisher-Key': 'a'*64}
        png = io.BytesIO()
        Image.new('RGB', (80, 80), 'red').save(png, format='PNG')
        self.assertEqual(self.client.post(route+'/cover', content=png.getvalue(), headers=owner).status_code, 200)
        local_copy = self.client.get(route+'/download').content
        for headers in ({}, {'X-Upload-Token': 'test-secret'}, {'X-Publisher-Key': 'b'*64}):
            self.assertEqual(self.client.delete(route, headers=headers).status_code, 403)
        self.assertEqual(len(self.client.get('/api/v1/voices?q=作者').json()), 1)
        self.assertEqual(self.client.delete(route, headers=owner).status_code, 200)
        timestamp = self.app.state.database.get(row['id'])['withdrawn_at']
        self.assertTrue(timestamp)
        with TestClient(create_app(data_dir=self.data)) as restarted:
            self.assertEqual(restarted.delete(route, headers=owner).status_code, 200)
            self.assertEqual(restarted.get('/api/v1/voices?q=作者').json(), [])
            self.assertEqual(restarted.get(route+'/download').status_code, 404)
            self.assertEqual(restarted.get(route+'/cover').status_code, 404)
            self.assertEqual(restarted.post(route+'/cover', content=png.getvalue(), headers=owner).status_code, 404)
        self.assertEqual(self.app.state.database.get(row['id'])['withdrawn_at'], timestamp)
        self.assertEqual(hashlib.sha256(local_copy).hexdigest(), row['package_sha256'])
        self.assertTrue((self.data / self.app.state.database.get(row['id'])['package_path']).is_file())

    def test_cover_racing_with_withdrawal_cannot_publish(self):
        row = self.upload().json()
        route = f'/api/v1/voices/{row["id"]}'
        png = io.BytesIO()
        Image.new('RGB', (80, 80), 'blue').save(png, format='PNG')
        database = self.app.state.database
        original = database.set_cover
        def race(voice_id, digest, owner):
            self.assertTrue(database.withdraw(voice_id, owner, '2026-09-16T00:00:00Z'))
            return original(voice_id, digest, owner)
        with patch.object(database, 'set_cover', side_effect=race):
            self.assertEqual(self.client.post(route+'/cover', content=png.getvalue(),
                                             headers={'X-Publisher-Key':'a'*64}).status_code, 404)
        self.assertIsNone(database.get(row['id'])['cover_sha256'])
        self.assertEqual(self.client.get(route+'/cover').status_code, 404)

    def test_unknown_legacy_owner_cannot_be_claimed(self):
        row = self.upload().json()
        with self.app.state.database.connect() as db:
            db.execute('UPDATE voices SET owner_key_hash=NULL WHERE id=?', (row['id'],))
        self.assertEqual(self.client.delete(f'/api/v1/voices/{row["id"]}',
                         headers={'X-Publisher-Key':'a'*64, 'X-Upload-Token':'test-secret'}).status_code, 403)
