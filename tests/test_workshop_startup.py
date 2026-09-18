from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import Mock, patch
import tempfile
from pathlib import Path

import app


class WorkshopStartupTests(TestCase):
    def test_local_startup_does_not_contact_or_start_workshop(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.object(app, 'PROJECT_ROOT', Path(directory)))
            for name in ('services.process_lifetime.install_process_lifetime_job',
                         'services.asset_service.recover_deletions', 'services.asset_service.migrate_ownership',
                         'services.history_service.backfill_snapshots', 'app.recover_tasks',
                         'services.ui_instance.register', 'services.ui_instance.unregister',
                         'adapters.inference_runtime.runtime.close', 'services.workshop_runtime.stop_local_services'):
                stack.enter_context(patch(name))
            stack.enter_context(patch.object(app, 'recover_history', return_value={}))
            demo = Mock(config={'app_id':'isolated-startup'})
            stack.enter_context(patch.object(app, 'build_app', return_value=demo))
            start = stack.enter_context(patch('services.workshop_runtime.ensure_local_service', side_effect=AssertionError('eager workshop')))
            connect = stack.enter_context(patch('services.workshop_client.WorkshopClient._client', side_effect=AssertionError('network')))
            app.main(port=17865)
            start.assert_not_called()
            connect.assert_not_called()
            demo.launch.assert_called_once()
