from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryItem:
    item_id: str
    text: str
    outcome: str | None = None
    eligible: bool = True
    decision_id: str | None = None


class RetrievalMemory:
    def __init__(self) -> None:
        self.items: list[MemoryItem] = []

    def add(self, item: MemoryItem) -> None:
        if item.eligible:
            self.items.append(item)

    def search(self, query: str, limit: int = 10):
        terms = set(query.lower().split())
        ranked = sorted(
            ((len(terms & set(i.text.lower().split())), i) for i in self.items),
            key=lambda x: x[0],
            reverse=True,
        )
        return [item for score, item in ranked[:limit] if score]
