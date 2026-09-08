from proxy_pipeline.agents.modes import (
    DebateConsensusMode,
    EnsembleJudgeMode,
    HumanInTheLoopMode,
    ManagerSubagentsMode,
    SingleAgentMode,
)
from proxy_pipeline.domain.models import DecisionContext
from proxy_pipeline.modes.registry import ModeManifest, ModeRegistry
from proxy_pipeline.modes.runtime import ModeRuntime


class Agent:
    def __init__(self, value):
        self.value = value

    def decide(self, context):
        return {"value": self.value, "snapshot_keys": sorted(context.snapshot)}


class Approver:
    def review(self, context, proposal):
        return {**proposal, "approved": True}


def context():
    return DecisionContext("candidate", "c", {"seed": 1}, "s", "m")


def test_all_required_modes_are_registered():
    registry = ModeRegistry()
    for name, mode_type in [
        ("a", "single_agent"),
        ("b", "manager_subagents"),
        ("c", "router"),
        ("d", "ensemble_judge"),
        ("e", "debate_consensus"),
        ("f", "human_in_loop"),
    ]:
        registry.register(ModeManifest(name, mode_type, "1", {}))
    registry.activate("a")
    runtime = ModeRuntime(registry)
    runtime.activate_at_checkpoint("b")
    assert runtime.current.name == "b"
    runtime.rollback()
    assert runtime.current.name == "a"


def test_single_and_manager_and_debate_and_hitl():
    ctx = context()
    assert SingleAgentMode(Agent(1)).decide(ctx)["value"] == 1
    manager = ManagerSubagentsMode(Agent(9), [Agent(2), Agent(3)]).decide(ctx)
    assert manager["value"] == 9
    debate = DebateConsensusMode([Agent("pro")], [Agent("con")], Agent("final")).decide(ctx)
    assert debate["value"] == "final"
    hitl = HumanInTheLoopMode(Agent(4), Approver()).decide(ctx)
    assert hitl["approved"] is True
