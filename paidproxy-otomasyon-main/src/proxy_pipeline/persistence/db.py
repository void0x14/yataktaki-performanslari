from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3

from proxy_pipeline.domain.time import utc_epoch_ms
from proxy_pipeline.persistence.schema import SCHEMA

SCHEMA_VERSION = "001_control_plane"


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    db.executescript(SCHEMA)
    checksum = sha256(SCHEMA.encode()).hexdigest()
    db.execute(
        "INSERT OR IGNORE INTO schema_migrations(version,checksum,applied_at) VALUES (?,?,?)",
        (SCHEMA_VERSION, checksum, utc_epoch_ms()),
    )
    db.commit()
    return db


def wal_checkpoint(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def quick_check(db: sqlite3.Connection) -> str:
    row = db.execute("PRAGMA quick_check").fetchone()
    return str(row[0]) if row else "unknown"


def integrity_check(db: sqlite3.Connection) -> str:
    row = db.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row else "unknown"
