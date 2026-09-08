"""Operator feedback persistence for the pipeline."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FeedbackItem:
    decision_id: str
    actor: str
    approval: str
    correction: str | None = None
    reason: str = ""
    before_action: str | None = None
    after_action: str | None = None
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FeedbackStore:
    """Small append-only store used by the API control plane."""

    def __init__(self, root: Path | str = Path("var/feedback")) -> None:
        self.root = Path(root)
        self.path = self.root / "operator-feedback.jsonl"

    def record(
        self,
        decision_id: str,
        actor: str,
        approval: str = "noted",
        correction: str | None = None,
        reason: str = "",
        before_action: str | None = None,
        after_action: str | None = None,
    ) -> FeedbackItem:
        item = FeedbackItem(
            decision_id=str(decision_id),
            actor=str(actor),
            approval=str(approval),
            correction=correction,
            reason=str(reason),
            before_action=before_action,
            after_action=after_action,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item.as_dict(), ensure_ascii=False) + "\n")
        return item


def save_bulgu(ip: str, port: int, protokol: str = "", kaynak: str = "", bulgu_dir: Path = Path("var/envanter")) -> Path:
    """Append a validated proxy finding for the pipeline's inventory."""
    bulgu_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    path = bulgu_dir / f"bulgu-{day}.jsonl"
    row = {"ip": str(ip), "port": int(port), "protokol": str(protokol or ""), "kaynak": str(kaynak or ""), "zaman": datetime.now().isoformat(timespec="seconds")}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")
    return path
