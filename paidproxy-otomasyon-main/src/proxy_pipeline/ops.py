from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3

from proxy_pipeline.persistence.db import integrity_check, wal_checkpoint


class BackupManager:
    def __init__(self, database: str | Path, root: str | Path) -> None:
        self.database = Path(database)
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def snapshot(self, name: str) -> Path:
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.database.exists():
            src = sqlite3.connect(self.database)
            try:
                dst = sqlite3.connect(target)
                try:
                    src.backup(dst)
                    wal_checkpoint(src)
                finally:
                    dst.close()
            finally:
                src.close()
        return target

    def verify(self, snapshot: str | Path) -> bool:
        path = Path(snapshot)
        if not path.exists() or path.stat().st_size <= 0:
            return False
        db = sqlite3.connect(path)
        try:
            return integrity_check(db) == "ok"
        finally:
            db.close()

    def restore(self, snapshot: str | Path, destination: str | Path | None = None) -> Path:
        dest = Path(destination or self.database)
        shutil.copy2(snapshot, dest)
        return dest
