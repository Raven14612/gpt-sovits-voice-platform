"""Inspect or apply independent-library metadata migration; never delete audio."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import asset_service, history_service
from services.storage_lock import metadata_lock


def main():
    parser = argparse.ArgumentParser(description="独立成品仓库与音色材料归属迁移")
    parser.add_argument("--apply", action="store_true", help="补全历史快照并保存音色组归属")
    args = parser.parse_args()
    if args.apply:
        asset_service.recover_deletions()
    before = {p.name: history_service.file_hash(p) for p in (ROOT / "data/outputs").glob("*.wav")}
    with metadata_lock():
        if args.apply:
            backfilled = history_service.backfill_snapshots()
            plans = asset_service.migrate_ownership()
        else:
            backfilled = 0
            index = ROOT / "data/index/voices.json"
            plans = [asset_service.deletion_plan(v["voice_id"], index) for v in asset_service.read_json(index)]
    after = {p.name: history_service.file_hash(p) for p in (ROOT / "data/outputs").glob("*.wav")}
    if before != after:
        raise RuntimeError("成品仓库内容发生变化，请检查并发操作。")
    report = {"applied": args.apply, "backfilled_results": backfilled, "outputs_unchanged": len(before),
              "voices": plans, "files_deleted": 0}
    if args.apply:
        asset_service.atomic_json(ROOT / "data/logs/storage-migration.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "voices"}, ensure_ascii=False))
    for plan in plans:
        print(f"{plan['display_name']}: {plan['files']} files / {plan['bytes'] / 1024**2:.1f} MiB")


if __name__ == "__main__":
    main()
