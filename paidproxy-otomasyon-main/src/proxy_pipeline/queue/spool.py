from __future__ import annotations

from pathlib import Path
from threading import Lock


class AppendOnlySpool:
    def __init__(self, path: str | Path, quota_bytes: int | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.quota_bytes = quota_bytes
        self._lock = Lock()

    def append(self, line: str) -> int:
        if "\n" in line:
            raise ValueError("one event per append")
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            if self.quota_bytes is not None and self.path.exists() and self.path.stat().st_size >= self.quota_bytes:
                raise OSError("spool quota exceeded")
            position = fh.tell()
            fh.write(line + "\n")
            fh.flush()
            return position

    def read_from(self, offset: int = 0):
        with self.path.open("r", encoding="utf-8") as fh:
            fh.seek(offset)
            while True:
                position = fh.tell()
                line = fh.readline()
                if not line:
                    break
                yield position, line.rstrip("\n")

    def size(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0
