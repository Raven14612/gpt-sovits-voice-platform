import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from setup.EnvironmentSetup.env_setup import checker as c


class EnvironmentSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / '中文 project'
        self.engine = self.root/'engine'
        self.engine.mkdir(parents=True)
        (self.root/'config').mkdir()
        (self.root/'app.py').write_text('# fixture')
        self.py = self.engine/'python.exe'
        self.py.write_bytes(b'fixture')
        self.config = self.root/'config/engine.local.json'
        self.config.write_text(json.dumps({'engine_root': 'engine', 'python_path': 'engine/python.exe',
                                          'profile': 'keep', 'custom': {'password': 'secret'}}), encoding='utf-8')

    def check(self, **kwargs):
        return c.run_check(self.root, ui_python=self.root/'ui/python.exe', report_path=False,
                           probe_dependencies=False, **kwargs)

    def test_bad_engine_is_fail_and_not_ready(self):
        report = self.check(engine_root='missing', include_gpu=False)
        self.assertEqual(report['summary'], 'FAIL')
        self.assertEqual(report['levels']['training'], 'NOT_READY')

    def test_disabled_gpu_is_not_verified_and_does_not_launch_probe(self):
        with patch.object(c, '_run') as run:
            report = self.check(include_gpu=False)
        run.assert_not_called()
        self.assertEqual(next(x for x in report['checks'] if x['key']=='cuda_tensor')['status'], 'NOT_VERIFIED')
        self.assertFalse(report['synthesis_executed'])

    def test_gpu_scope_accepts_only_rtx50(self):
        for name, expected in [('NVIDIA GeForce RTX 5060 Laptop GPU', 'PASS'),
                               ('NVIDIA GeForce RTX 4060 Laptop GPU', 'FAIL')]:
            with self.subTest(gpu=name), patch.object(c, '_run', return_value=(0,
                    c.MARKER + json.dumps({'ok': True, 'tensor_sum': 4096.0, 'gpu_name': name,
                                          'free_bytes': 6*1024**3, 'total_bytes': 8*1024**3}), 1)):
                report = self.check()
            scope = next(row for row in report['checks'] if row['key'] == 'gpu_scope')
            self.assertEqual(scope['status'], expected)

    def test_cpu_only_cuda_failure_and_timeout_block_readiness(self):
        for code, data in [(1, {'ok': False, 'error': 'CPU-only Torch'}),
                           (1, {'ok': False, 'error': 'CUDA operation failed'}),
                           (-2, None)]:
            with self.subTest(code=code, data=data), patch.object(c, '_run', return_value=(
                    code, c.MARKER+json.dumps(data) if data else 'timeout', 150)):
                report = self.check()
            item = next(x for x in report['checks'] if x['key']=='cuda_tensor')
            self.assertEqual(item['status'], 'FAIL')
            self.assertEqual(item['actual']['exit_code'], code)

    def test_real_subprocess_timeout_is_bounded(self):
        result = c._run([sys.executable, '-c', 'import time; time.sleep(20)'], timeout=.15)
        self.assertEqual(result[0], -2)

    def test_real_port_owner_is_left_alive(self):
        with socket.socket() as owner:
            owner.bind(('127.0.0.1', 0)); owner.listen()
            port = owner.getsockname()[1]
            report = self.check(include_gpu=False, port=port)
            self.assertEqual(next(x for x in report['checks'] if x['key']=='port')['status'], 'WARN')
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                pass

    def test_missing_and_same_size_corrupted_model_are_detected(self):
        model = self.engine/'base.pth'
        model.write_bytes(b'good')
        manifest = {'files': [{'path':'base.pth','bytes':4,'sha256':c.sha256(model),
                     'groups':['training'],'source':'https://example.test/model'}]}
        (self.root/'config/environment-resources.json').write_text(json.dumps(manifest))
        for content in [b'evil', None]:
            if content is None:
                model.unlink()
            else:
                model.write_bytes(content)
            report = self.check(include_gpu=False)
            item = next(x for x in report['checks'] if x['key']=='resource:base.pth')
            self.assertEqual(item['status'], 'FAIL')
            self.assertIn('sha256', item['actual'])

    def test_readiness_levels_are_independent(self):
        checks = [{'groups':['base'],'status':'PASS'}, {'groups':['inference'],'status':'PASS'},
                  {'groups':['training'],'status':'FAIL'}]
        self.assertEqual(c.readiness(checks, ['base','inference']), 'READY')
        self.assertEqual(c.readiness(checks, ['base','training']), 'NOT_READY')
        checks.append({'groups':['inference'],'status':'NOT_VERIFIED'})
        self.assertEqual(c.readiness(checks, ['base','inference']), 'NOT_VERIFIED')

    def test_new_config_apply_and_exact_rollback(self):
        original = self.config.read_bytes()
        preview = c.config_preview(self.root, self.engine, self.py)
        preview['after']['profile'] = 'new-profile'; preview['changed'] = True
        transaction = c.apply_config(self.root, preview)
        self.assertEqual(json.loads(self.config.read_bytes())['custom'], {'password':'secret'})
        c.rollback(self.root, transaction)
        self.assertEqual(self.config.read_bytes(), original)
        self.config.unlink()
        preview = c.config_preview(self.root, self.engine, self.py)
        transaction = c.apply_config(self.root, preview)
        self.assertTrue(self.config.is_file())
        c.rollback(self.root, transaction)
        self.assertFalse(self.config.exists())

    def test_preview_preserves_files_and_detects_concurrent_edit(self):
        before = self.config.read_bytes()
        preview = c.config_preview(self.root, self.engine, self.py)
        self.assertEqual(self.config.read_bytes(), before)
        self.config.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'changed since preview'):
            c.apply_config(self.root, preview)
        self.assertEqual(self.config.read_text(), '{}')

    def test_config_disk_failure_keeps_original(self):
        from services import path_migration as m
        before = self.config.read_bytes()
        preview = c.config_preview(self.root, self.engine, self.py)
        preview['after']['profile']='new'; preview['changed']=True
        replace = m.os.replace
        def fail(src, dst):
            if Path(dst) == self.config:
                raise OSError('disk failure')
            return replace(src,dst)
        with patch.object(m.os, 'replace', side_effect=fail), self.assertRaises(OSError):
            c.apply_config(self.root, preview)
        self.assertEqual(self.config.read_bytes(), before)

    def test_invalid_config_is_not_discarded(self):
        self.config.write_text('not json')
        report = self.check(include_gpu=False, write_config=True)
        self.assertEqual(report['summary'], 'FAIL')
        self.assertEqual(self.config.read_text(), 'not json')

    def test_public_report_omits_paths_secrets_and_raw_error_text(self):
        report = self.check(include_gpu=False)
        report['checks'][0]['actual']={'token':'secret','path':str(self.root)}
        report['checks'][0]['message']='user=person token=secret'
        public=json.dumps(c.sanitized_report(report))
        for secret in [str(self.root), 'secret', 'password', 'person', 'custom']:
            self.assertNotIn(secret, public)
        target=self.root/'report.json'
        c.save_report(report,target)
        self.assertEqual(json.loads(target.read_text(encoding='utf-8')),report)
        self.assertEqual(json.loads(target.with_name('report-sanitized.json').read_text(encoding='utf-8')), c.sanitized_report(report))

    def test_gradio_import_error_is_reported_instead_of_missing_diagnostic(self):
        ui=self.root/'ui/python.exe';ui.parent.mkdir();ui.write_bytes(b'fixture')
        with patch.object(c,'_run',return_value=(1,"ENV_SETUP_RESULT={\"ok\":false,\"error\":\"ModuleNotFoundError: gradio\"}",12)):
            report=c.run_check(self.root,ui_python=ui,engine_root=self.engine,engine_python=self.py,report_path=False,include_gpu=False)
        self.assertEqual(report['summary'],'FAIL')
        self.assertTrue(any(x['key']=='ui_imports' and x['status']=='FAIL' for x in report['checks']))


if __name__ == '__main__':
    unittest.main()
