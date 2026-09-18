from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import gradio as gr

from models.schemas import AppError
from services.workshop_presentation import cover_html, card_caption, installed_voice
from types import SimpleNamespace
from ui import workshop_page as page


ROW = dict(id='00000000-0000-0000-0000-000000000001', display_name='测试 <script>', author='作者',
           description='简介', license_name='CC BY 4.0', created_at='2026-09-15', emotions=['neutral'],
           package_bytes=123, package_sha256='a'*64)


class WorkshopPageTests(TestCase):
    def test_withdraw_requires_owner_confirmation_and_preserves_local_assets(self):
        owner = dict(ROW, can_withdraw=True)
        with patch.object(page, 'WorkshopClient') as client, patch.object(page.workshop_library, 'change_installation') as local:
            self.assertIn('仅上传者', page.withdraw_selected(ROW['id'], [ROW], True)[3])
            self.assertIn('确认', page.withdraw_selected(ROW['id'], [owner], False)[3])
            client.assert_not_called()
            result = page.withdraw_selected(ROW['id'], [owner], True)
            client.return_value.withdraw_voice.assert_called_once_with(ROW['id'])
            self.assertEqual(result[0], [])
            self.assertFalse(result[2]['visible'])
            local.assert_not_called()
        with patch.object(page, 'current_installation', return_value=None):
            result = page.open_card_dialog({'id': ROW['id'], 'action': 'details'}, [owner])
            self.assertTrue(result[10]['visible'])
            self.assertFalse(result[11])
            self.assertFalse(page.open_card_dialog({'id': ROW['id'], 'action': 'details'}, [ROW])[10]['visible'])

    def test_card_escapes_metadata_and_embeds_valid_cover(self):
        client = Mock(cover_image=Mock(return_value=None))
        image = cover_html(ROW, client)
        self.assertIn('data:image/webp;base64,', image)
        self.assertNotIn('<script>', image)
        self.assertIn('&lt;script&gt;', card_caption(ROW, None))
        self.assertIn('未安装', card_caption(ROW, None))

    def test_stale_card_action_is_ignored(self):
        result = page.open_card('missing', 'install', [ROW])
        self.assertTrue(all('value' not in item for item in result))
        result = page.open_card(ROW['id'], 'details', [ROW])
        self.assertEqual(result[0], ROW['id'])
        self.assertTrue(result[2]['visible'])
        self.assertFalse(result[6]['visible'])
        self.assertIn('&lt;script&gt;', result[3])

    def test_install_status_uses_package_hash_not_name_or_remote_id(self):
        wrong = SimpleNamespace(origin_type='workshop', package_hash='b'*64, status='verified')
        local = SimpleNamespace(origin_type='local_training', package_hash=ROW['package_sha256'], status='verified')
        self.assertIsNone(installed_voice(ROW, [wrong, local]))
        match = SimpleNamespace(origin_type='workshop', package_hash=ROW['package_sha256'], status='deleted')
        self.assertIs(installed_voice(ROW, [wrong, match]), match)
        self.assertIn('在回收站', card_caption(ROW, match))

    def test_installed_card_never_offers_install_and_resets_cover(self):
        source = SimpleNamespace(voice_id='original', origin_type='local_training', status='verified')
        row = dict(ROW, local_voice_id='original', can_edit_cover=True)
        with patch.object(page, 'current_installation', return_value=source):
            result = page.open_card(ROW['id'], 'install', [row])
        self.assertEqual(result[1], 'details')
        self.assertFalse(result[5]['visible'])
        self.assertFalse(result[6]['visible'])
        self.assertIsNone(result[8])
        self.assertEqual(result[9], '')
        self.assertIn('已安装', result[3])

    def test_uploaded_source_uninstall_uses_existing_reversible_service(self):
        source = SimpleNamespace(voice_id='original', origin_type='local_training', status='verified')
        row = dict(ROW, local_voice_id='original')
        self.assertIs(installed_voice(row, [source]), source)
        with patch.object(page.voice_service, 'list_voices', return_value=[source]), \
                patch.object(page.voice_service, 'set_voice_deleted') as delete:
            self.assertEqual(page.workshop_library.change_installation(row, True), 'original')
            delete.assert_called_once_with('original', True, page.voice_service.VOICE_INDEX)
        source.status = 'deleted'
        self.assertIs(installed_voice(row, [source]), source)
        self.assertIn('未安装', card_caption(row, source))

    def test_cover_controls_and_callback_reject_non_owner(self):
        result = page.open_card(ROW['id'], 'details', [ROW])
        self.assertFalse(result[4]['visible'])
        with patch.object(page, 'WorkshopClient') as client:
            result = page.save_cover(ROW['id'], [ROW], 'cover.png', 'shared-token')
            self.assertIn('仅上传者', result[1])
            client.assert_not_called()
        owner = dict(ROW, can_edit_cover=True)
        self.assertTrue(page.open_card(ROW['id'], 'details', [owner])[4]['visible'])

    def test_offline_and_empty_search_clear_grid(self):
        with patch.object(page, 'WorkshopClient') as client:
            client.return_value.list_voices.return_value = []
            result = page.refresh_workshop(None)
            client.return_value.list_voices.assert_called_once_with('', limit=100)
            self.assertEqual(result[0], [])
            self.assertIsNone(result[1])
            client.return_value.list_voices.side_effect = AppError('WORKSHOP_UNAVAILABLE', '无法连接')
            result = page.refresh_workshop('empty')
            self.assertIn('WORKSHOP_UNAVAILABLE', result[2])

    def test_download_uses_selected_record_hash(self):
        with patch.object(page, 'WorkshopClient') as client, patch.object(page.packages, 'inspect_voice_package') as inspect:
            client.return_value.download_voice.return_value = 'download.rvoice'
            inspect.return_value = dict(manifest=dict(voice=ROW, license=dict(name='CC BY 4.0')), package_sha256='a'*64)
            result = page.download_selected(ROW['id'], [ROW], None)
            client.return_value.download_voice.assert_called_once_with(ROW['id'], expected_size=123, expected_sha256='a'*64)
            self.assertEqual(result[0]['id'], ROW['id'])
            self.assertFalse(result[2])

    def test_install_requires_confirmation_before_downloading(self):
        with patch.object(page, 'current_installation', return_value=None), \
                patch.object(page, 'download_selected') as download:
            result = list(page.run_card_action(ROW['id'], 'install', [ROW], False, 1, None))
            download.assert_not_called()
            self.assertIn('INSTALL_CONFIRM_REQUIRED', result[-1][4]['value'])
            self.assertTrue(result[-1][5]['interactive'])

    def test_already_installed_guard_prevents_duplicate_download(self):
        source = SimpleNamespace(status='verified')
        with patch.object(page, 'current_installation', return_value=source), \
                patch.object(page, 'download_selected') as download:
            result = list(page.run_card_action(ROW['id'], 'install', [ROW], True, 1, None))
            download.assert_not_called()
            self.assertIn('ALREADY_INSTALLED', result[-1][4]['value'])

    def test_restore_does_not_download_and_updates_selection(self):
        source = SimpleNamespace(status='deleted', origin_type='workshop')
        with patch.object(page, 'current_installation', return_value=source), \
                patch.object(page.workshop_library, 'change_installation', return_value='restored') as restore, \
                patch.object(page, 'voice_choices', return_value=[('恢复', 'restored')]), \
                patch.object(page, 'download_selected') as download:
            result = list(page.run_card_action(ROW['id'], 'install', [ROW], False, 1, None))[-1]
            restore.assert_called_once_with(ROW, False)
            download.assert_not_called()
            self.assertEqual(result[0], 2)
            self.assertEqual(result[1], 'restored')
            self.assertFalse(result[5]['visible'])

    def test_failed_install_cleans_download_and_allows_retry(self):
        with patch.object(page, 'current_installation', return_value=None), \
                patch.object(page, 'download_selected', return_value=({'path':'package.rvoice','hash':'a'*64}, '', False, {})), \
                patch.object(page.packages, 'inspect_voice_package', return_value={'package_sha256':'a'*64}), \
                patch.object(page.packages, 'install_voice_package', side_effect=AppError('CHECKPOINT_UNSAFE', '校验失败')), \
                patch.object(page, 'cleanup_package') as cleanup:
            result = list(page.run_card_action(ROW['id'], 'install', [ROW], True, 1, None))[-1]
            self.assertIn('CHECKPOINT_UNSAFE', result[4]['value'])
            self.assertTrue(result[5]['interactive'])
            cleanup.assert_called_once_with('package.rvoice', area='tmp/workshop-downloads')

    def test_upload_feedback_precedes_work_and_cleanup_preserves_success(self):
        with TemporaryDirectory() as directory:
            package = Path(directory) / 'voice.rvoice'
            package.write_bytes(b'package')
            with patch.object(page.packages, 'export_voice_package', return_value=package) as export, \
                    patch.object(page, 'WorkshopClient') as client, \
                    patch.object(page, 'cleanup_package', side_effect=PermissionError('busy')):
                client.return_value.upload_voice.return_value = {'id': ROW['id']}
                updates = page.upload_selected('local', 'author', 'description', 'CC BY 4.0', True, '')
                first = next(updates)
                export.assert_not_called()
                self.assertIn('正在校验', first[0])
                self.assertFalse(first[1]['interactive'])
                second = next(updates)
                client.return_value.upload_voice.assert_not_called()
                self.assertIn('正在上传', second[0])
                last = next(updates)
                self.assertIn('上传成功', last[0])
                self.assertIn('暂时无法清理', last[0])
                self.assertTrue(last[1]['interactive'])
                self.assertEqual(last[2], ROW['id'])

    def test_upload_failure_restores_button_and_never_refreshes(self):
        with patch.object(page.packages, 'export_voice_package', side_effect=AppError('RIGHTS_REQUIRED', '请确认权利')), \
                patch.object(page, 'WorkshopClient') as client:
            last = list(page.upload_selected('local', 'a', 'd', 'CC BY 4.0', False, ''))[-1]
            self.assertIn('RIGHTS_REQUIRED', last[0])
            self.assertTrue(last[1]['interactive'])
            self.assertIsNone(last[2])
            client.assert_not_called()
            self.assertTrue(all('value' not in update for update in page.refresh_after_upload(None)))

    def test_uploaded_voice_refresh_clears_previous_search(self):
        with patch.object(page, 'refresh_workshop', return_value=([], {}, '已刷新')) as refresh:
            result = page.refresh_after_upload(ROW['id'])
            refresh.assert_called_once_with('')
            self.assertEqual(result[0], '')
