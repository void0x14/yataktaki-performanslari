from __future__ import annotations

from typing import Iterable, Protocol

from proxy_pipeline.domain.models import DecisionContext


class Agent(Protocol):
    def decide(self, context: DecisionContext) -> dict: ...


class SingleAgentMode:
    """Mod A — one model uses all discovery tools and produces final actions."""

    version = "single_agent"

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    def decide(self, context: DecisionContext) -> dict:
        return self.agent.decide(context)


class ManagerSubagentsMode:
    """Mod B — manager distributes source/network/history/high-value/critic work."""

    version = "manager_subagents"

    def __init__(self, manager: Agent, specialists: Iterable[Agent]) -> None:
        self.manager = manager
        self.specialists = tuple(specialists)

    def decide(self, context: DecisionContext) -> dict:
        research = [agent.decide(context) for agent in self.specialists]
        enriched = DecisionContext(
            context.decision_type,
            context.candidate_id,
            {**context.snapshot, "specialist_outputs": research},
            context.strategy_version,
            context.mode_version,
            context.correlation_id,
        )
        return self.manager.decide(enriched)


class RouterMode:
    """Mod C — routes by decision type / context / user preference."""

    version = "router"

    def __init__(self, resolver, role: str = "decision") -> None:
        self.resolver = resolver
        self.role = role

    def decide(self, context: DecisionContext) -> dict:
        handler = self.resolver.resolve(self.role)
        return handler.decide(context)


class EnsembleJudgeMode:
    """Mod D — independent rankings plus a judge."""

    version = "ensemble_judge"

    def __init__(self, agents: Iterable[Agent], judge: Agent) -> None:
        self.agents = tuple(agents)
        self.judge = judge

    def decide(self, context: DecisionContext) -> dict:
        outputs = [agent.decide(context) for agent in self.agents]
        enriched = DecisionContext(
            context.decision_type,
            context.candidate_id,
            {**context.snapshot, "candidate_outputs": outputs},
            context.strategy_version,
            context.mode_version,
            context.correlation_id,
        )
        return self.judge.decide(enriched)


class DebateConsensusMode:
    """Mod E — pro/con arguments then a finalizer."""

    version = "debate_consensus"

    def __init__(self, proponents: Iterable[Agent], opponents: Iterable[Agent], finalizer: Agent) -> None:
        self.proponents = tuple(proponents)
        self.opponents = tuple(opponents)
        self.finalizer = finalizer

    def decide(self, context: DecisionContext) -> dict:
        pro = [agent.decide(context) for agent in self.proponents]
        con = [agent.decide(context) for agent in self.opponents]
        enriched = DecisionContext(
            context.decision_type,
            context.candidate_id,
            {**context.snapshot, "arguments_for": pro, "arguments_against": con},
            context.strategy_version,
            context.mode_version,
            context.correlation_id,
        )
        return self.finalizer.decide(enriched)


class HumanInTheLoopMode:
    """Mod F — AI proposes; operator amends/approves. Correction becomes training data."""

    version = "human_in_loop"

    def __init__(self, agent: Agent, approver) -> None:
        self.agent = agent
        self.approver = approver

    def decide(self, context: DecisionContext) -> dict:
        proposal = self.agent.decide(context)
        return self.approver.review(context, proposal)
