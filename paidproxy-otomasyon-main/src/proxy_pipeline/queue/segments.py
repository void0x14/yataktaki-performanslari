from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import json

import zstandard as zstd

from proxy_pipeline.domain.ids import new_uuid7
from proxy_pipeline.domain.states import SegmentState


@dataclass
class Segment:
    segment_id: str
    manifest_id: str
    path: Path
    cursor: int = 0
    state: str = SegmentState.CREATED.value
    lease_owner: str | None = None
    lease_until: int | None = None
    item_count: int = 0
    retry_count: int = 0
    schema_version: str = "1"
    checksum_value: str = ""

    @property
    def checksum(self) -> str:
        if self.path.exists():
            return sha256(self.path.read_bytes()).hexdigest()
        return self.checksum_value

    def checkpoint(self) -> None:
        checkpoint = self.path.with_suffix(self.path.suffix + ".checkpoint")
        checkpoint.write_text(
            json.dumps(
                {
                    "cursor": self.cursor,
                    "state": self.state,
                    "lease_owner": self.lease_owner,
                    "lease_until": self.lease_until,
                    "retry_count": self.retry_count,
                },
                sort_keys=True,
            )
            + "\n"
        )

    def recover(self) -> None:
        checkpoint = self.path.with_suffix(self.path.suffix + ".checkpoint")
        if checkpoint.exists():
            data = json.loads(checkpoint.read_text())
            self.cursor = int(data["cursor"])
            self.state = data["state"]
            self.lease_owner = data.get("lease_owner")
            self.lease_until = data.get("lease_until")
            self.retry_count = int(data.get("retry_count", 0))


def write_segment_items(path: Path, items: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in items).encode()
    compressed = zstd.ZstdCompressor(level=3).compress(payload)
    path.write_bytes(compressed)
    return sha256(compressed).hexdigest()


def read_segment_items(path: Path) -> list[dict]:
    data = zstd.ZstdDecompressor().decompress(path.read_bytes())
    if not data:
        return []
    return [json.loads(line) for line in data.decode().splitlines() if line]


def new_segment_id() -> str:
    return new_uuid7()
