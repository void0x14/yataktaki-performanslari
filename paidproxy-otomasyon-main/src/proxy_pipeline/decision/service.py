from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Protocol
from uuid import uuid4

from proxy_pipeline.decision.contracts import DecisionItemPlan, DecisionOutput, TargetPlan
from proxy_pipeline.domain.models import Action, Decision, DecisionContext, DecisionItem, DecisionState, Target
from proxy_pipeline.state import DecisionLifecycle


class DecisionRoute(Protocol):
    version: str

    def decide(self, context: DecisionContext) -> dict: ...


class DecisionBlocked(RuntimeError):
    """No configured AI route is available; no semantic fallback is permitted."""


@dataclass
class DecisionRecord:
    state: DecisionState
    decision: Decision | None = None
    schema_result: str | None = None
    reused: bool = False
    parent_decision_id: str | None = None
    lifecycle: DecisionLifecycle = field(default_factory=DecisionLifecycle)


class DecisionService:
    """Synchronous Stage-1 decision service. No scanner, socket, or hardcoded score."""

    def __init__(
        self,
        routes: list[DecisionRoute] | None = None,
        *,
        payload_store=None,
        writer=None,
        event_bus=None,
    ) -> None:
        self.routes = routes or []
        self.payload_store = payload_store
        self.writer = writer
        self.event_bus = event_bus
        self.ledger: dict[tuple[str, str, str], DecisionRecord] = {}
        self.by_id: dict[str, DecisionRecord] = {}

    def decide(self, context: DecisionContext, *, fresh: bool = False) -> DecisionRecord:
        key = (context.context_hash, context.strategy_version, context.mode_version)
        if not fresh and key in self.ledger and self.ledger[key].state == DecisionState.COMMITTED:
            reused = self.ledger[key]
            reused.reused = True
            return reused
        if not self.routes:
            record = DecisionRecord(DecisionState.DECISION_BLOCKED)
            self.ledger[key] = record
            self._persist(context, record)
            raise DecisionBlocked("no AI route is configured")
        raw = None
        last_error: Exception | None = None
        for route in self.routes:
            try:
                raw = route.decide(context)
                break
            except Exception as exc:
                last_error = exc
                continue
        if raw is None:
            record = DecisionRecord(DecisionState.DECISION_BLOCKED)
            self.ledger[key] = record
            self._persist(context, record)
            raise DecisionBlocked(f"all AI routes are unavailable: {last_error}")
        try:
            parsed = DecisionOutput.model_validate(raw)
            decision = self._to_decision(parsed, context, raw)
        except Exception as exc:
            record = DecisionRecord(DecisionState.INVALID_OUTPUT, schema_result="invalid")
            self.ledger[key] = record
            self._persist(context, record)
            raise ValueError("AI output failed the decision contract") from exc
        if not decision.items:
            raise ValueError("batch output requires a decision item per candidate")
        record = DecisionRecord(DecisionState.VALIDATED, decision, schema_result="ok")
        if record.state == DecisionState.VALIDATED:
            if fresh and key in self.ledger and self.ledger[key].decision:
                decision = Decision(
                    **{
                        **decision.__dict__,
                        "parent_decision_id": self.ledger[key].decision.decision_id,
                    }
                )
                record.decision = decision
                record.parent_decision_id = decision.parent_decision_id
                self.ledger[key].state = DecisionState.SUPERSEDED
            record.state = DecisionState.COMMITTED
        self.ledger[key] = record
        self.by_id[decision.decision_id] = record
        self._persist(context, record)
        return record

    def _persist(self, context: DecisionContext, record: DecisionRecord) -> None:
        if self.writer is not None:
            self.writer.write_decision(context, record)

    @staticmethod
    def _to_decision(parsed: DecisionOutput, context: DecisionContext, raw: dict) -> Decision:
        items = parsed.items
        if not items:
            items = [
                DecisionItemPlan(
                    candidate_id=context.candidate_id,
                    action=parsed.action,
                    targets=parsed.targets,
                    order_index=0,
                    resource_allocation=parsed.resource_plan,
                    stop_expression=parsed.stop_condition,
                    reassessment_expression=parsed.reassessment,
                )
            ]
        targets = tuple(_target(t) for item in items for t in item.targets) or tuple(_target(t) for t in parsed.targets)
        raw_bytes = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        return Decision(
            decision_id=parsed.decision_id or str(uuid4()),
            action=parsed.action,
            targets=targets,
            resource_plan=parsed.resource_plan,
            stop_condition=parsed.stop_condition,
            reassessment=parsed.reassessment,
            expected_value=parsed.expected_value,
            confidence=parsed.confidence,
            evidence=tuple(parsed.evidence),
            counter_evidence=tuple(parsed.counter_evidence),
            risks=tuple(parsed.risks),
            context_hash=context.context_hash,
            mode_version=context.mode_version,
            strategy_version=context.strategy_version,
            raw_response_ref=parsed.raw_response_ref,
            items=tuple(
                DecisionItem(
                    candidate_id=item.candidate_id,
                    action=item.action,
                    targets=tuple(_target(t) for t in item.targets),
                    order_index=item.order_index,
                    resource_allocation=item.resource_allocation,
                    stop_expression=item.stop_expression,
                    reassessment_expression=item.reassessment_expression,
                    status=item.status,
                )
                for item in items
            ),
            alternatives=tuple(parsed.alternatives),
            requested_tools=tuple(parsed.requested_tools),
            raw_response_hash=sha256(raw_bytes).hexdigest(),
            provider=parsed.provider,
            model=parsed.model,
            prompt_version=context.prompt_version or None,
            tool_version=context.tool_version or None,
        )


def _target(plan: TargetPlan | dict) -> Target:
    if isinstance(plan, dict):
        plan = TargetPlan.model_validate(plan)
    return Target(
        cidr=plan.cidr,
        ports=tuple(plan.ports),
        protocols=tuple(plan.protocols),
        asn=plan.asn,
        prefix=plan.prefix,
        sample_approach=plan.sample_approach,
    )
