"""Preview by default; apply changes or restore an immutable migration backup."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.path_migration import ACTIVE_FILES, apply_changes, preview, rollback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', metavar='TRANSACTION_DIRECTORY')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--from-root', action='append', default=[])
    parser.add_argument('--file', action='append', choices=ACTIVE_FILES)
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        if args.rollback:
            transaction = rollback(root, args.rollback)
            report = {'mode': 'rollback', 'restore_transaction': str(transaction) if transaction else None}
        else:
            changes, report = preview(root, from_roots=args.from_root, files=args.file or ACTIVE_FILES)
            report['mode'] = 'apply' if args.apply else 'preview'
            if args.apply:
                if report['missing_paths'] or report['external_paths']:
                    report['error'] = 'Resolve missing/external active resources before applying.'
                    print(json.dumps(report, ensure_ascii=False, indent=2))
                    return 1
                transaction = apply_changes(root, changes)
                report['transaction'] = str(transaction) if transaction else None
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
