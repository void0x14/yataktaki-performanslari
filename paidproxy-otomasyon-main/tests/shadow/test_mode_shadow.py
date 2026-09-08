from proxy_pipeline.agents.modes import EnsembleJudgeMode, SingleAgentMode
from proxy_pipeline.domain.models import DecisionContext


class Agent:
    def __init__(self, action):
        self.action = action

    def decide(self, context):
        return {"action": self.action}


def test_same_context_can_be_shadowed_across_modes():
    context = DecisionContext("candidate", "c", {"x": 1}, "s", "m")
    single = SingleAgentMode(Agent("sample")).decide(context)
    ensemble = EnsembleJudgeMode([Agent("sample"), Agent("defer")], Agent("sample")).decide(context)
    assert single["action"] == ensemble["action"]
