from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

from proxy_pipeline.domain.ids import new_uuid7
from proxy_pipeline.domain.time import utc_epoch_ms

EVENT_TYPES = (
    "source.fetched",
    "candidate.discovered",
    "context.ready",
    "decision.requested",
    "decision.completed",
    "decision.invalid",
    "manifest.committed",
    "scan.started",
    "l4.open",
    "l7.validated",
    "l7.failed",
    "evidence.ready",
    "decision.outcome_attached",
    "asset.assessed",
    "mode.changed",
    "route.failed",
    "rate_limit.tripped",
    "scan.paused",
    "alert.raised",
)


@dataclass(frozen=True)
class Event:
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    schema_version: str = "1"
    event_id: str = ""
    occurred_at: int = 0
    producer: str = "proxy-pipeline"
    correlation_id: str = ""
    causation_id: str = ""
    severity: str = "info"
    decision_id: str = ""
    decision_item_id: str = ""
    manifest_id: str = ""
    run_id: str = ""
    segment_id: str = ""
    mode_version: str = ""
    strategy_version: str = ""
    payload_ref: str = ""
    payload_summary: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            object.__setattr__(self, "event_id", new_uuid7() if False else str(uuid4()))
        if not self.occurred_at:
            object.__setattr__(self, "occurred_at", utc_epoch_ms(datetime.now(timezone.utc)))
        if not self.correlation_id:
            object.__setattr__(self, "correlation_id", self.event_id)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
