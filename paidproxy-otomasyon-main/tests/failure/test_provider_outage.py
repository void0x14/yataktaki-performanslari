import pytest

from proxy_pipeline.decision.service import DecisionBlocked, DecisionService
from proxy_pipeline.domain.models import DecisionContext


class Boom:
    version = "x"

    def decide(self, context):
        raise TimeoutError("model timeout")


def test_provider_outage_blocks_stage1():
    with pytest.raises(DecisionBlocked):
        DecisionService([Boom()]).decide(DecisionContext("candidate", "c", {}, "s", "m"))
