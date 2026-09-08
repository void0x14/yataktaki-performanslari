from proxy_pipeline.agents.modes import EnsembleJudgeMode
from proxy_pipeline.domain.models import DecisionContext


class Agent:
    def __init__(self, value):
        self.value = value

    def decide(self, context):
        return {"value": self.value}


def test_ensemble_passes_outputs_to_judge():
    context = DecisionContext("candidate", "c", {}, "s", "m")
    result = EnsembleJudgeMode([Agent(1), Agent(2)], Agent(3)).decide(context)
    assert result["value"] == 3
