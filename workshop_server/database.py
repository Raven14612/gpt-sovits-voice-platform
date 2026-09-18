import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, root):
        self.path = Path(root) / "workshop.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS voices (
                id TEXT PRIMARY KEY, display_name TEXT NOT NULL, author TEXT NOT NULL,
                description TEXT NOT NULL, license_name TEXT NOT NULL, engine_family TEXT NOT NULL,
                model_version TEXT NOT NULL, emotions_json TEXT NOT NULL, package_path TEXT NOT NULL UNIQUE,
                package_sha256 TEXT NOT NULL UNIQUE, package_bytes INTEGER NOT NULL, created_at TEXT NOT NULL,
                download_count INTEGER NOT NULL DEFAULT 0)""")
            if "cover_sha256" not in {row[1] for row in db.execute("PRAGMA table_info(voices)")}:
                db.execute("ALTER TABLE voices ADD COLUMN cover_sha256 TEXT")
            if "owner_key_hash" not in {row[1] for row in db.execute("PRAGMA table_info(voices)")}:
                db.execute("ALTER TABLE voices ADD COLUMN owner_key_hash TEXT")
            if "withdrawn_at" not in {row[1] for row in db.execute("PRAGMA table_info(voices)")}:
                db.execute("ALTER TABLE voices ADD COLUMN withdrawn_at TEXT")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def public(row):
        value = dict(row)
        value.pop("package_path", None)
        value.pop("owner_key_hash", None)
        value["emotions"] = json.loads(value.pop("emotions_json"))
        return value

    def list(self, query="", limit=50, offset=0, owner_key_hash=None):
        with self.connect() as db:
            # User percent/underscore characters are literal search text.
            q = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            rows = db.execute("""SELECT * FROM voices WHERE withdrawn_at IS NULL AND (display_name LIKE ? ESCAPE '\\'
                OR author LIKE ? ESCAPE '\\') ORDER BY created_at DESC, id LIMIT ? OFFSET ?""", (q, q, limit, offset)).fetchall()
        return [dict(self.public(row), can_edit_cover=bool(owner_key_hash and row['owner_key_hash'] == owner_key_hash),
                     can_withdraw=bool(owner_key_hash and row['owner_key_hash'] == owner_key_hash)) for row in rows]

    def get(self, voice_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM voices WHERE id=?", (voice_id,)).fetchone()
        return dict(row) if row else None

    def insert(self, row):
        fields = ("id", "display_name", "author", "description", "license_name", "engine_family", "model_version",
                  "emotions_json", "package_path", "package_sha256", "package_bytes", "created_at", "owner_key_hash")
        with self.connect() as db:
            db.execute("INSERT INTO voices (" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ")",
                       [row[key] for key in fields])
        return self.public(self.get(row["id"]))

    def downloaded(self, voice_id):
        with self.connect() as db:
            db.execute("UPDATE voices SET download_count=download_count+1 WHERE id=?", (voice_id,))

    def set_cover(self, voice_id, digest, owner_key_hash):
        with self.connect() as db:
            return db.execute("UPDATE voices SET cover_sha256=? WHERE id=? AND owner_key_hash=? AND withdrawn_at IS NULL",
                              (digest, voice_id, owner_key_hash)).rowcount == 1

    def withdraw(self, voice_id, owner_key_hash, timestamp):
        with self.connect() as db:
            # Ownership and the first withdrawal time are checked in the same transaction.
            return db.execute("UPDATE voices SET withdrawn_at=COALESCE(withdrawn_at, ?) WHERE id=? AND owner_key_hash=?",
                              (timestamp, voice_id, owner_key_hash)).rowcount == 1
