from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LedgerEntry:
    decision_id: str
    context_hash: str
    state: str
    event_id: str
    strategy_version: str = ""
    mode_version: str = ""
    parent_decision_id: str | None = None


class DecisionLedger:
    def __init__(self) -> None:
        self.entries: dict[str, LedgerEntry] = {}
        self.by_identity: dict[tuple[str, str, str], LedgerEntry] = {}

    def append(self, entry: LedgerEntry) -> None:
        if entry.decision_id in self.entries:
            raise ValueError("decision id already exists")
        self.entries[entry.decision_id] = entry
        if entry.context_hash:
            self.by_identity[(entry.context_hash, entry.strategy_version, entry.mode_version)] = entry

    def get(self, decision_id: str) -> LedgerEntry | None:
        return self.entries.get(decision_id)

    def lookup(self, context_hash: str, strategy_version: str, mode_version: str) -> LedgerEntry | None:
        return self.by_identity.get((context_hash, strategy_version, mode_version))
