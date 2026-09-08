from __future__ import annotations

from time import time_ns
from uuid import UUID, uuid4


def new_uuid7() -> str:
    """External correlation identifier (MASTER-PLAN §12.2)."""
    try:
        from uuid import uuid7  # type: ignore[attr-defined]

        return str(uuid7())
    except Exception:
        # Python < 3.14 fallback: RFC 9562 UUIDv7 layout with random tail.
        unix_ms = time_ns() // 1_000_000
        rand = uuid4().int & ((1 << 62) - 1)
        value = (unix_ms << 80) | (0x7 << 76) | ((rand >> 62) << 64) | (0x2 << 62) | (rand & ((1 << 62) - 1))
        return str(UUID(int=value & ((1 << 128) - 1)))


def new_internal_id() -> int:
    """Placeholder for SQLite INTEGER PRIMARY KEY assignment."""
    return 0
