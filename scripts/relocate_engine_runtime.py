"""Preview/fix the verified bundle's absolute site-package import paths."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.path_migration import apply_changes
from services.project_paths import resolve_project_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    raw = json.loads((ROOT / 'config/engine.local.json').read_text(encoding='utf-8'))
    engine = resolve_project_path(raw['engine_root'])
    python = resolve_project_path(raw['python_path'])
    site = python.parent / 'Lib/site-packages'
    changes = {}
    checks = []
    import os
    for file in site.glob('*.pth'):
        lines = file.read_text(encoding='utf-8-sig').splitlines()
        converted = []
        for line in lines:
            if line.strip() and not line.startswith(('#', 'import ')) and Path(line).is_absolute():
                target = resolve_project_path(line)
                if not target.is_relative_to(engine) or not target.is_dir():
                    raise ValueError(f'Unmapped/missing runtime import: {file.name}: {line}')
                relative = Path(os.path.relpath(target, site)).as_posix()
                checks.append({'file': file.name, 'before': line, 'after': relative})
                converted.append(relative)
            else:
                converted.append(line)
        if converted != lines:
            changes[file.relative_to(ROOT).as_posix()] = ('\n'.join(converted)+'\n').encode('utf-8')
    report = {'changes': checks, 'mode': 'apply' if args.apply else 'preview'}
    if args.apply:
        transaction = apply_changes(ROOT, changes)
        report['transaction'] = str(transaction) if transaction else None
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
