import hashlib
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import httpx
from PIL import Image

from models.schemas import AppError
from services.workshop_client import WorkshopClient, load_config
from services.workshop_runtime import ensure_local_service, stop_local_services
from workshop_server.tests.helpers import make_package


class WorkshopClientTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(stop_local_services)
        self.root = Path(self.tmp.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.config = dict(load_config(root=self.root), base_url=f'http://127.0.0.1:{port}', auto_start_local=True)
        self.client = WorkshopClient(config=self.config, root=self.root)

    def test_local_start_upload_cover_download_restart(self):
        self.assertEqual(self.client.health()['status'], 'ok')
        package = make_package(self.root / 'voice.rvoice')
        row = self.client.upload_voice(package, local_voice_id='original-voice')
        image = self.root / 'cover.png'
        Image.new('RGB', (100, 200), '#123456').save(image)
        self.client.set_cover(row['id'], image)
        rows = self.client.list_voices()
        self.assertTrue(rows[0]['can_edit_cover'])
        self.assertEqual(rows[0]['local_voice_id'], 'original-voice')
        self.assertTrue(rows[0]['cover_sha256'])
        cover = self.client.cover_image(rows[0])
        self.assertEqual(cover.size, (640, 400))
        self.assertEqual(cover.getpixel((0, 0)), (18, 52, 86))
        downloaded = self.client.download_voice(row['id'], expected_sha256=row['package_sha256'], expected_size=row['package_bytes'])
        self.assertEqual(hashlib.sha256(downloaded.read_bytes()).hexdigest(), row['package_sha256'])
        stop_local_services()
        self.client = WorkshopClient(config=self.config, root=self.root)
        self.assertEqual(self.client.list_voices()[0]['id'], row['id'])
        self.assertTrue(self.client.list_voices()[0]['can_edit_cover'])
        self.client.set_cover(row['id'], image)
        self.assertEqual(self.client.cover_image(self.client.list_voices()[0]).size, (640, 400))

        other = WorkshopClient(config=dict(self.config, auto_start_local=False), root=self.root / 'other')
        other_row = other.list_voices()[0]
        self.assertFalse(other_row['can_edit_cover'])
        self.assertNotIn('local_voice_id', other_row)
        with self.assertRaises(AppError) as denied:
            other.set_cover(row['id'], image, self.client._upload_token())
        self.assertEqual(denied.exception.code, 'COVER_FORBIDDEN')
        with self.assertRaises(AppError) as denied:
            other.withdraw_voice(row['id'])
        self.assertEqual(denied.exception.code, 'WITHDRAW_FORBIDDEN')
        self.client.withdraw_voice(row['id'])
        self.client.withdraw_voice(row['id'])
        stop_local_services()
        self.assertEqual(self.client.list_voices(), [])
        self.assertEqual(other.list_voices(), [])
        self.assertEqual(hashlib.sha256(downloaded.read_bytes()).hexdigest(), row['package_sha256'])
        with self.assertRaises(AppError) as missing:
            other.download_voice(row['id'])
        self.assertEqual(missing.exception.code, 'VOICE_NOT_FOUND')

    def test_default_does_not_start_development_server(self):
        config = load_config(root=self.root)
        self.assertIs(config['auto_start_local'], False)
        with patch('services.workshop_runtime.socket.socket') as sock:
            self.assertEqual(ensure_local_service(config, self.root), '')
            sock.assert_not_called()

    def test_remote_and_disabled_service_do_not_start(self):
        with patch('services.workshop_runtime.socket.socket') as sock:
            for config in (dict(self.config, base_url='https://example.com'), dict(self.config, auto_start_local=False)):
                self.assertEqual(ensure_local_service(config, self.root), '')
            sock.assert_not_called()

    def test_occupied_port_is_not_taken_over(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', int(self.config['base_url'].rsplit(':', 1)[1])))
            sock.listen()
            self.assertEqual(ensure_local_service(self.config, self.root), '')
            self.assertFalse((self.root / 'data/workshop').exists())

    def test_download_hash_failure_removes_partial(self):
        def respond(request):
            return httpx.Response(200, content=b'bad', headers={'Content-Length': '3'})
        client = WorkshopClient(root=self.root, config=self.config, transport=httpx.MockTransport(respond))
        with self.assertRaises(AppError):
            client.download_voice('00000000-0000-0000-0000-000000000001', expected_size=3, expected_sha256='0'*64)
        self.assertEqual(list((self.root / 'data/tmp/workshop-downloads').iterdir()), [])

    def test_bad_optional_cover_falls_back(self):
        client = WorkshopClient(root=self.root, config=self.config, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'bad')))
        self.assertIsNone(client.cover_image(dict(id='00000000-0000-0000-0000-000000000001', cover_sha256='0'*64)))

    def test_legacy_directory_is_preserved(self):
        legacy = self.root / 'workshop_data'
        legacy.mkdir()
        self.client.health()
        self.assertTrue((legacy / 'workshop.sqlite3').exists())
        self.assertFalse((self.root / 'data/workshop').exists())
