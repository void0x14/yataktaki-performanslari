from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Evidence:
    source: str
    kind: str
    value: object
    confidence: str
    observed_at: int
    payload_hash: str
    untrusted: bool = False


class EvidenceAggregator:
    def snapshot(self, records: Iterable[Evidence]) -> dict:
        items = tuple(records)
        return {
            "evidence": [e.__dict__ for e in items],
            "sources": sorted({e.source for e in items}),
            "conflicts": self.conflicts(items),
            "untrusted": [e.source for e in items if e.untrusted],
        }

    @staticmethod
    def conflicts(records):
        grouped: dict[str, set[str]] = {}
        for item in records:
            grouped.setdefault(item.kind, set()).add(str(item.value))
        return {kind: sorted(values) for kind, values in grouped.items() if len(values) > 1}
