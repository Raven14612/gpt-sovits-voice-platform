import subprocess
from unittest import TestCase

from models.schemas import AppError
from services.engine_service import load_engine_config
from services.project_paths import PROJECT_ROOT, project_environment


class CheckpointSanitizerTests(TestCase):
    def test_legacy_config_restricted_loading_in_model_runtime(self):
        try:
            config = load_engine_config()
        except AppError:
            self.skipTest('Model runtime is not configured')
        if not config.python_path.is_file():
            self.skipTest('Model runtime is not installed')
        env = project_environment(root=PROJECT_ROOT, python=config.python_path, engine_root=config.engine_root)
        env['CUDA_VISIBLE_DEVICES'] = ''
        result = subprocess.run([str(config.python_path), str(PROJECT_ROOT / 'tests/checkpoint_sanitizer_probe.py'),
                                 str(PROJECT_ROOT)], env=env, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertIn(b'PASS:', result.stdout)
