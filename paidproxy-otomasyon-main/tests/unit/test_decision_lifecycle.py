from __future__ import annotations


import pytest

from proxy_pipeline.decision.service import DecisionBlocked, DecisionService
from proxy_pipeline.domain.models import DecisionContext, DecisionState


def sample_output(cidr="198.51.100.0/28", action="sample"):
    return {
        "action": action,
        "targets": [{"cidr": cidr, "ports": [3128], "protocols": ["http_connect"]}],
        "resource_plan": {"addresses": 16, "approach": "context-specific"},
        "stop_condition": {"when": "evidence.ready"},
        "evidence": ["peeringdb network type"],
        "counter_evidence": [],
        "risks": ["stale bgp"],
        "items": [
            {
                "candidate_id": "c-1",
                "action": action,
                "targets": [{"cidr": cidr, "ports": [3128], "protocols": ["http_connect"]}],
                "order_index": 0,
                "resource_allocation": {"addresses": 16},
                "stop_expression": {"when": "evidence.ready"},
            }
        ],
    }


class StubRoute:
    version = "stub-1"

    def __init__(self, payload):
        self.payload = payload

    def decide(self, context):
        return dict(self.payload)


class FailingRoute:
    version = "fail-1"

    def decide(self, context):
        raise RuntimeError("provider 429")


def context():
    return DecisionContext("candidate", "c-1", {"asn": 64500}, "s1", "m1")


def test_committed_decision_is_reused_in_reproducible_mode():
    service = DecisionService([StubRoute(sample_output())])
    first = service.decide(context())
    second = service.decide(context())
    assert first.decision.decision_id == second.decision.decision_id
    assert second.reused is True
    assert first.state is DecisionState.COMMITTED


def test_fresh_reevaluation_records_parent():
    service = DecisionService([StubRoute(sample_output())])
    first = service.decide(context())
    second = service.decide(context(), fresh=True)
    assert second.decision.parent_decision_id == first.decision.decision_id
    assert second.reused is False


def test_invalid_output_does_not_commit():
    service = DecisionService([StubRoute({"action": "not-a-real-action"})])
    with pytest.raises(ValueError):
        service.decide(context())
    record = service.ledger[context().decision_identity]
    assert record.state is DecisionState.INVALID_OUTPUT




def test_all_routes_failing_blocks_without_hardcoded_fallback():
    service = DecisionService([FailingRoute(), FailingRoute()])
    with pytest.raises(DecisionBlocked):
        service.decide(context())
