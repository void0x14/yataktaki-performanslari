
import pytest

from proxy_pipeline.decision.service import DecisionBlocked, DecisionService
from proxy_pipeline.domain.models import DecisionContext, Target
from proxy_pipeline.manifests.builder import ManifestBuilder


def context():
    return DecisionContext("candidate", "c-1", {"z": 1, "a": 2}, "s1", "m1")


def test_context_hash_is_canonical():
    a = context()
    b = DecisionContext("candidate", "c-1", {"a": 2, "z": 1}, "s1", "m1")
    assert a.context_hash == b.context_hash


def test_no_ai_route_blocks_without_fallback():
    with pytest.raises(DecisionBlocked):
        DecisionService().decide(context())

