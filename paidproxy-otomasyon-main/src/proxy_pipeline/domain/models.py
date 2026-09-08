from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from proxy_pipeline.domain.ids import new_uuid7


class DecisionState(StrEnum):
    REQUESTED = "REQUESTED"
    CONTEXT_READY = "CONTEXT_READY"
    INFERENCE_RUNNING = "INFERENCE_RUNNING"
    VALIDATED = "VALIDATED"
    COMMITTED = "COMMITTED"
    EXECUTED = "EXECUTED"
    OUTCOME_ATTACHED = "OUTCOME_ATTACHED"
    DECISION_BLOCKED = "DECISION_BLOCKED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class Action(StrEnum):
    RESEARCH = "research"
    SAMPLE = "sample"
    EXPAND = "expand"
    FULL_SCAN = "full_scan"
    DEFER = "defer"
    DROP = "drop"
    REASSESS = "reassess"
    DEEP_TEST = "deep_test"


@dataclass(frozen=True)
class Target:
    cidr: str
    ports: tuple[int, ...]
    protocols: tuple[str, ...] = ()
    asn: int | None = None
    prefix: str | None = None
    sample_approach: str | None = None


@dataclass(frozen=True)
class DecisionContext:
    decision_type: str
    candidate_id: str
    snapshot: dict[str, Any]
    strategy_version: str
    mode_version: str
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    prompt_version: str = ""
    tool_version: str = ""
    model_version: str = ""
    provider_version: str = ""

    @property
    def canonical_json(self) -> str:
        return json.dumps(self.snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def context_hash(self) -> str:
        return sha256(self.canonical_json.encode()).hexdigest()

    @property
    def decision_identity(self) -> tuple[str, str, str]:
        return self.context_hash, self.strategy_version, self.mode_version


@dataclass(frozen=True)
class DecisionItem:
    candidate_id: str
    action: Action
    targets: tuple[Target, ...]
    order_index: int
    resource_allocation: dict[str, Any]
    stop_expression: dict[str, Any]
    reassessment_expression: dict[str, Any] | None = None
    status: str = "pending"


@dataclass(frozen=True)
class Decision:
    decision_id: str
    action: Action
    targets: tuple[Target, ...]
    resource_plan: dict[str, Any]
    stop_condition: dict[str, Any]
    reassessment: dict[str, Any] | None
    expected_value: str | None
    confidence: str | None
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    risks: tuple[str, ...]
    context_hash: str
    mode_version: str
    strategy_version: str
    raw_response_ref: str | None = None
    items: tuple[DecisionItem, ...] = ()
    alternatives: tuple[str, ...] = ()
    requested_tools: tuple[str, ...] = ()
    parent_decision_id: str | None = None
    prompt_payload_ref: str | None = None
    prompt_hash: str | None = None
    raw_response_hash: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    tool_version: str | None = None


@dataclass(frozen=True)
class ExecutionManifest:
    manifest_id: str
    decision_id: str
    targets: tuple[Target, ...]
    technical_profile: dict[str, Any]
    immutable: bool = True
    protocol_intent: tuple[str, ...] = ()
    segment_plan: dict[str, Any] = field(default_factory=dict)
    status: str = "committed"

    def __post_init__(self) -> None:
        if not self.immutable:
            raise ValueError("execution manifests are immutable")
        if not self.decision_id:
            raise ValueError("manifest requires an AI decision id")


def new_decision_id() -> str:
    return new_uuid7()
