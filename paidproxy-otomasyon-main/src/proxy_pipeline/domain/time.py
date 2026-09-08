from __future__ import annotations

from datetime import datetime, timezone


def utc_epoch_ms(now: datetime | None = None) -> int:
    """UTC epoch millisecond as specified in MASTER-PLAN §12.2."""
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)
