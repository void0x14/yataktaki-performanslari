from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import zstandard as zstd


class PayloadStore:
    """Immutable zstandard payload store; SQLite keeps only ref and checksum."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._cctx = zstd.ZstdCompressor(level=3)
        self._dctx = zstd.ZstdDecompressor()

    def put(self, payload: str | bytes | dict) -> str:
        import json

        if isinstance(payload, dict):
            data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        elif isinstance(payload, str):
            data = payload.encode()
        else:
            data = payload
        digest = sha256(data).hexdigest()
        path = self.root / f"{digest}.zst"
        if not path.exists():
            path.write_bytes(self._cctx.compress(data))
        return digest

    def get(self, ref: str) -> bytes:
        path = self.root / f"{ref}.zst"
        if not path.exists():
            gz = self.root / f"{ref}.json.gz"
            if gz.exists():
                import gzip

                data = gzip.open(gz, "rb").read()
                if sha256(data).hexdigest() != ref:
                    raise ValueError("payload checksum mismatch")
                return data
            raise FileNotFoundError(ref)
        data = self._dctx.decompress(path.read_bytes())
        if sha256(data).hexdigest() != ref:
            raise ValueError("payload checksum mismatch")
        return data
