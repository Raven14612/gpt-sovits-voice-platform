from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts import assemble_release as release


class ReleaseAssemblyTests(TestCase):
    def test_source_allowlist_excludes_user_data_local_config_and_cache(self):
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            for name in [*release.FILES, *('config/'+n for n in release.CONFIGS), *('scripts/'+n for n in release.SCRIPTS),
                         'data/private/workshop-publishers.json', 'config/workshop.local.json', 'models/emotion/private.bin',
                         'services/__pycache__/secret.pyc', 'services/service.py', '_archive/private.py',
                         'third_party/vendor/LICENSE', 'third_party/vendor/weights.pth']:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture', encoding='utf-8')
            selected = {p.relative_to(root).as_posix() for p in release.select_files(root, 'source')}
            self.assertIn('services/service.py', selected)
            self.assertIn('third_party/vendor/LICENSE', selected)
            self.assertIn('scripts/assemble_release.py', selected)
            self.assertFalse(any(p.startswith(('data/', '_archive/', 'models/emotion/')) for p in selected))
            self.assertNotIn('config/workshop.local.json', selected)
            self.assertNotIn('services/__pycache__/secret.pyc', selected)
            self.assertNotIn('third_party/vendor/weights.pth', selected)

    def test_refuses_existing_or_nested_destination_before_copy(self):
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()/'project'
            root.mkdir()
            with patch.object(release, 'select_files') as select:
                for path in (root, root/'build', root.parent):
                    with self.assertRaises(ValueError):
                        release.assemble(root, path, 'source')
                existing = root.parent/'existing'
                existing.mkdir()
                with self.assertRaises(FileExistsError):
                    release.assemble(root, existing, 'source')
                select.assert_not_called()
