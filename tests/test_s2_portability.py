import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services import path_migration as migration
from services.project_paths import project_environment, resolve_project_path


class S2PortabilityTests(unittest.TestCase):
    def test_training_utf8_option_propagates_to_embedded_python_worker(self):
        import subprocess
        from types import SimpleNamespace
        from services import training_preparation_service as preparation
        engine_python = Path(__file__).resolve().parents[1]/'engines/verified-v2pro/runtime/python.exe'
        if not engine_python.exists():
            self.skipTest('Requires embedded model runtime')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()/'中文 训练'
            run = root/'data/training/fixture'
            run.mkdir(parents=True)
            plan = run/'plan.json'
            plan.write_text(json.dumps({'status':'prepared_not_executed','dataset_id':'dataset','voice_id':'voice'}), encoding='utf-8')
            config = SimpleNamespace(python_path=engine_python, engine_root=engine_python.parent, profile='test')
            with patch.object(preparation, 'PROJECT_ROOT', root), patch.object(preparation, '_load_config', return_value=config), \
                 patch.object(preparation, 'materialize_training_configs', return_value=(run/'s1.yaml', run/'s2.json')), \
                 patch.object(preparation, '_training_references', return_value=[]):
                params = preparation.training_parameters(plan, SimpleNamespace(dataset_id='dataset'), '测试', 'task')
            fixture = run/'中文配置.json'
            fixture.write_text('{"text":"中文路径"}', encoding='utf-8')
            script = run/'spawn_probe.py'
            script.write_text("import sys,multiprocessing,json\n"
                              "def worker():\n"
                              " assert sys.flags.utf8_mode == 1\n"
                              " with open(sys.argv[1]) as f: assert json.load(f)['text']=='中文路径'\n"
                              "if __name__=='__main__':\n"
                              " p=multiprocessing.get_context('spawn').Process(target=worker); p.start(); p.join(20)\n"
                              " if p.is_alive(): p.terminate(); p.join(); raise RuntimeError('worker timeout')\n"
                              " assert p.exitcode==0\n", encoding='utf-8')
            for key in ('gpt_command', 'sovits_command'):
                command = params[key]
                index = next(i for i, arg in enumerate(command) if arg.endswith('_train.py'))
                result = subprocess.run(command[:index]+[str(script), str(fixture)], capture_output=True,
                                        text=True, encoding='utf-8', errors='replace', timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_launcher_fails_for_missing_or_shared_model_interpreter(self):
        from scripts import launch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()/'root'
            self.fixture(root)
            ui = root/'runtimes/ui/python.exe'
            ui.parent.mkdir(parents=True)
            ui.write_bytes(b'fixture')
            config = root/'config/engine.local.json'
            with patch.object(launch, 'ROOT', root), patch.object(launch.sys, 'executable', str(ui)):
                config.write_bytes(migration.encoded({'engine_root': 'engine', 'python_path': 'missing.exe'}))
                with self.assertRaisesRegex(ValueError, 'missing'):
                    launch.preflight()
                config.write_bytes(migration.encoded({'engine_root': 'engine', 'python_path': 'runtimes/ui/python.exe'}))
                with self.assertRaisesRegex(ValueError, 'separate'):
                    launch.preflight()

    def test_launcher_reports_model_interpreter_timeout(self):
        from scripts import launch
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()/'root'
            self.fixture(root)
            config = root/'config/engine.local.json'
            config.write_bytes(migration.encoded({'engine_root': 'engine', 'python_path': 'engine/python.exe'}))
            with patch.object(launch, 'ROOT', root), patch.object(launch.sys, 'executable', str(root/'runtimes/ui/python.exe')), \
                 patch.object(launch.subprocess, 'run', side_effect=subprocess.TimeoutExpired('model', 30)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    launch.preflight()

    def test_moved_training_configs_are_materialized_without_editing_originals(self):
        from services import training_preparation_service as preparation
        import yaml
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()/'new'
            old = self.fixture(root)
            (root/'config/path-migration.json').write_bytes(migration.encoded({'aliases': [
                {'old_root': str(old), 'new_relative_root': '.'}]}))
            run = root/'data/training/run'
            run.mkdir(parents=True)
            original = migration.encoded({'train': {'half_weights_save_dir': str(old/'data/training/run/GPT_weights')},
                                         'pretrained_s1': str(old/'engine/base.ckpt'), 'remark': str(old/'notes')})
            (run/'s1.yaml').write_bytes(original)
            (run/'s2.json').write_bytes(migration.encoded({'data': {'exp_dir': str(old/'data/training/run/experiment')}}))
            with patch.object(preparation, 'PROJECT_ROOT', root):
                s1, s2 = preparation.materialize_training_configs(run)
            self.assertEqual((run/'s1.yaml').read_bytes(), original)
            self.assertEqual(yaml.safe_load(s1.read_text())['pretrained_s1'], str(root/'engine/base.ckpt'))
            self.assertEqual(json.loads(s2.read_text())['data']['exp_dir'], str(run/'experiment'))
            self.assertEqual(yaml.safe_load(s1.read_text())['remark'], str(old/'notes'))

    def fixture(self, root):
        old = root.parent / 'old project'
        (root / 'config').mkdir(parents=True)
        (root / 'engine').mkdir()
        (root / 'engine/python.exe').write_bytes(b'fixture')
        config = {'engine_root': str(old / 'engine'), 'python_path': str(old / 'engine/python.exe'),
                  'notes': str(old / 'notes.wav'), 'unknown': {'version': 'preserve'}}
        (root / 'config/engine.local.json').write_bytes(migration.encoded(config))
        return old

    def test_preview_apply_idempotent_and_exact_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / '中文 space'
            old = self.fixture(root)
            original = (root / 'config/engine.local.json').read_bytes()
            changes, report = migration.preview(root, from_roots=[old], files=['config/engine.local.json'])
            self.assertFalse(report['missing_paths'])
            self.assertEqual((root / 'config/engine.local.json').read_bytes(), original)
            transaction = migration.apply_changes(root, changes)
            config = json.loads((root / 'config/engine.local.json').read_bytes())
            self.assertEqual(config['engine_root'], 'engine')
            self.assertEqual(config['notes'], str(old / 'notes.wav'))
            self.assertEqual(config['unknown'], {'version': 'preserve'})
            self.assertFalse(migration.preview(root, from_roots=[old], files=['config/engine.local.json'])[0])
            migration.rollback(root, transaction)
            self.assertEqual((root / 'config/engine.local.json').read_bytes(), original)
            self.assertFalse((root / 'config/path-migration.json').exists())
            migration.rollback(root, transaction)

    def test_failed_second_replace_restores_first_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'one.json').write_bytes(b'one')
            (root / 'two.json').write_bytes(b'two')
            real_write = migration.atomic_write
            def failing_write(path, data):
                if path == root / 'two.json' and data == b'new-two':
                    raise OSError('injected disk failure')
                return real_write(path, data)
            with patch.object(migration, 'atomic_write', side_effect=failing_write):
                with self.assertRaises(OSError):
                    migration.apply_changes(root, {'one.json': b'new-one', 'two.json': b'new-two'})
            self.assertEqual((root / 'one.json').read_bytes(), b'one')
            self.assertEqual((root / 'two.json').read_bytes(), b'two')

    def test_rollback_conflict_is_checked_before_restoring_any_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'one').write_bytes(b'one')
            (root / 'two').write_bytes(b'two')
            transaction = migration.apply_changes(root, {'one': b'new-one', 'two': b'new-two'})
            (root / 'two').write_bytes(b'user edit')
            with self.assertRaisesRegex(ValueError, 'conflict'):
                migration.rollback(root, transaction)
            self.assertEqual((root / 'one').read_bytes(), b'new-one')
            self.assertEqual((root / 'two').read_bytes(), b'user edit')

    def test_missing_resources_reported_and_invalid_schema_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'root'
            old = self.fixture(root)
            (root / 'engine/python.exe').unlink()
            _, report = migration.preview(root, from_roots=[old], files=['config/engine.local.json'])
            self.assertEqual(report['missing_paths'][0]['field'], 'python_path')
            config = root / 'config/engine.local.json'
            config.write_text('{"engine_root": null}', encoding='utf-8')
            with self.assertRaises(ValueError):
                migration.preview(root, files=['config/engine.local.json'])
            self.assertEqual(config.read_text(), '{"engine_root": null}')

    def test_specific_alias_wins_and_missing_target_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'new'
            old = self.fixture(root)
            (old / 'engine').mkdir(parents=True)
            (old / 'engine/only-old.wav').write_bytes(b'old')
            (root / 'config/path-migration.json').write_bytes(migration.encoded({'aliases': [
                {'old_root': str(old), 'new_relative_root': '.'},
                {'old_root': str(old / 'engine'), 'new_relative_root': 'engine'}]}))
            moved = resolve_project_path(old / 'engine/only-old.wav', root=root)
            self.assertEqual(moved, root / 'engine/only-old.wav')
            self.assertFalse(moved.exists())

    def test_environment_drops_foreign_python_and_uses_project_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.dict(os.environ, {'PYTHONHOME': 'foreign', 'PYTHONPATH': 'foreign'}):
                env = project_environment(root=root, python=root/'runtime/python.exe', engine_root=root/'engine')
            self.assertNotIn('PYTHONHOME', env)
            self.assertNotIn('foreign', env['PYTHONPATH'])
            for key in ['TEMP', 'TMP', 'GRADIO_TEMP_DIR', 'HF_HOME', 'MODELSCOPE_CACHE', 'TORCH_HOME']:
                self.assertTrue(Path(env[key]).is_relative_to(root))
                self.assertTrue(Path(env[key]).is_dir())

    def test_alias_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'new'
            old = self.fixture(root)
            (root/'config/path-migration.json').write_bytes(migration.encoded({'aliases': [
                {'old_root': str(old), 'new_relative_root': '../outside'}]}))
            with self.assertRaises(ValueError):
                resolve_project_path(old/'engine', root=root)


if __name__ == '__main__':
    unittest.main()
