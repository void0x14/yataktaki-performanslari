from __future__ import annotations

from pathlib import Path

import pytest

from proxy_pipeline.domain.models import DecisionContext, Target


@pytest.fixture
def decision_context() -> DecisionContext:
    return DecisionContext("candidate", "c-1", {"z": 1, "a": 2}, "s1", "m1")


@pytest.fixture
def sample_target() -> Target:
    return Target("198.51.100.0/28", (3128,), ("http_connect",))

import pytest as _pt

@_pt.fixture(autouse=True)
def yerlesik_beyinle_sinirla(request, monkeypatch):
    if request.node.get_closest_marker("havuz_canli"):
        return
    import proxy_pipeline.agents.ai_havuz as _H
    def _suskun(self, context):
        raise RuntimeError("sınama: dış havuz kapalı")
    monkeypatch.setattr(_H.HavuzBeyni, "decide", _suskun)
