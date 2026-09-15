"""Schema-scoped migration with immutable backups and conflict-aware rollback."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from services.project_paths import resolve_project_path

PATH_KEYS = {"engine_root", "python_path", "ui_python", "source_path", "slice_dir",
             "list_path", "emotions_path", "feature_manifest", "gpt_weight", "sovits_weight",
             "audio_path", "output_path", "log_path", "pretrained_s1", "pretrained_s2G",
             "pretrained_s2D", "exp_dir", "s2_ckpt_dir", "save_weight_dir",
             "half_weights_save_dir", "train_semantic_path", "train_phoneme_path", "output_dir"}
ACTIVE_FILES = ("config/engine.local.json", "data/index/datasets.json", "data/index/voices.json")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".migration-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def inside(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path outside project: {name}")
    return path


def resolve_with_aliases(value, root, aliases):
    path = Path(value).expanduser()
    if path.is_absolute():
        for alias in sorted(aliases, key=lambda item: len(Path(item['old_root']).parts), reverse=True):
            target = inside(root, alias['new_relative_root'])
            if Path(alias['new_relative_root']).is_absolute():
                raise ValueError("Alias target must be relative")
            try:
                suffix = path.resolve().relative_to(Path(alias['old_root']).resolve())
            except ValueError:
                continue
            return inside(root, target / suffix)
    return (root / path).resolve()


def convert_fields(value, resolver, *, relative_root=None, findings=None, field=""):
    """Only documented path fields change; text, provenance and unknown fields survive."""
    if isinstance(value, dict):
        return {key: convert_fields(item, resolver, relative_root=relative_root,
                                   findings=findings, field=key) for key, item in value.items()}
    if isinstance(value, list):
        return [convert_fields(item, resolver, relative_root=relative_root,
                               findings=findings, field=field) for item in value]
    if field in PATH_KEYS and isinstance(value, str) and value:
        path = resolver(value)
        external = relative_root is not None and not path.is_relative_to(relative_root)
        if findings is not None:
            findings.append({"field": field, "original": value, "resolved": str(path),
                             "exists": path.exists(), "external": external})
        if relative_root is not None:
            return value if external else path.relative_to(relative_root).as_posix()
        return str(path)
    return value


def preview(root, *, from_roots=(), files=ACTIVE_FILES):
    root = Path(root).resolve()
    mapping_path = root / "config/path-migration.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {
        "schema_version": 1, "aliases": []}
    original_mapping = encoded(mapping)
    for old in from_roots:
        old = Path(old).resolve()
        if not any(Path(item["old_root"]) == old for item in mapping["aliases"]):
            mapping["aliases"].append({"old_root": old.as_posix(), "new_relative_root": "."})
    resolver = lambda value: resolve_with_aliases(value, root, mapping["aliases"])
    changes, checks = {}, []
    if encoded(mapping) != original_mapping:
        changes["config/path-migration.json"] = encoded(mapping)
    for name in files:
        if name not in ACTIVE_FILES:
            raise ValueError("Only active config/dataset/voice indexes may be rewritten; historical files are preserved.")
        path = inside(root, name)
        if not path.is_file():
            raise ValueError(f"Required migration source missing: {name}")
        original = json.loads(path.read_text(encoding="utf-8"))
        # Validate before writing, retaining the original dictionary including extra fields.
        from models.schemas import DatasetRecord, EngineConfig, VoiceProfile
        schema = EngineConfig if name.startswith("config/") else DatasetRecord if "datasets" in name else VoiceProfile
        if schema is EngineConfig:
            schema.model_validate(original)
        else:
            if not isinstance(original, list):
                raise ValueError(f"Expected list: {name}")
            for row in original:
                schema.model_validate(row)
        findings = []
        converted = convert_fields(original, resolver, relative_root=root, findings=findings)
        checks.extend({"file": name, **item} for item in findings)
        if converted != original:
            changes[name] = encoded(converted)
    report = {"changed_files": list(changes), "checks": checks,
              "missing_paths": [item for item in checks if not item["exists"]],
              "external_paths": [item for item in checks if item["external"]],
              "historical_files": "Preserved byte-for-byte; resolve via path-migration.json."}
    return changes, report


def apply_changes(root, changes):
    root = Path(root).resolve()
    if not changes:
        return None
    transaction = root / "data/migrations" / uuid4().hex
    transaction.mkdir(parents=True, exist_ok=False)
    entries = []
    for name, data in changes.items():
        path = inside(root, name)
        before = path.read_bytes() if path.exists() else None
        backup = transaction / name
        if before is not None:
            atomic_write(backup, before)
        entries.append({"file": name, "existed": before is not None,
                        "before_sha256": digest(before) if before is not None else None,
                        "after_sha256": digest(data)})
    journal = {"status": "prepared", "entries": entries}
    atomic_write(transaction / "transaction.json", encoded(journal))
    written = []
    try:
        for entry in entries:
            name = entry["file"]
            path = inside(root, name)
            current = digest(path.read_bytes()) if path.exists() else None
            if current != entry["before_sha256"]:
                raise ValueError(f"Migration source changed: {name}")
            atomic_write(path, changes[name])
            written.append(entry)
        journal["status"] = "applied"
        atomic_write(transaction / "transaction.json", encoded(journal))
    except Exception:
        for entry in reversed(written):
            path = inside(root, entry["file"])
            if entry["existed"]:
                atomic_write(path, (transaction / entry["file"]).read_bytes())
            else:
                path.unlink(missing_ok=True)
        journal["status"] = "rolled_back_after_failure"
        atomic_write(transaction / "transaction.json", encoded(journal))
        raise
    return transaction


def rollback(root, transaction):
    root = Path(root).resolve()
    transaction = inside(root, transaction)
    if not transaction.is_relative_to(root / "data/migrations"):
        raise ValueError("Rollback requires a project data/migrations transaction")
    journal = json.loads((transaction / "transaction.json").read_text(encoding="utf-8"))
    changes = {}
    for item in journal["entries"]:
        path = inside(root, item["file"])
        current = digest(path.read_bytes()) if path.exists() else None
        if current == item["before_sha256"]:
            continue
        if current != item["after_sha256"]:
            raise ValueError(f"Rollback conflict; file edited since migration: {item['file']}")
        if item["existed"]:
            backup = inside(transaction, item["file"]).read_bytes()
            if digest(backup) != item["before_sha256"]:
                raise ValueError("Backup checksum mismatch")
            changes[item["file"]] = backup
    # Keep a second transaction so a restore is itself reviewable and reversible.
    restore = apply_changes(root, changes)
    for item in journal["entries"]:
        if not item["existed"]:
            inside(root, item["file"]).unlink(missing_ok=True)
    journal["status"] = "rolled_back"
    atomic_write(transaction / "transaction.json", encoded(journal))
    return restore
