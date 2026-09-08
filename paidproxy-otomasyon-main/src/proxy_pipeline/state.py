from __future__ import annotations

from dataclasses import dataclass, field

from proxy_pipeline.domain.states import (
    CANDIDATE_TRANSITIONS,
    DECISION_TRANSITIONS,
    SEGMENT_TRANSITIONS,
    CandidateState,
    DecisionState,
    SegmentState,
)


@dataclass
class StateMachine:
    state: CandidateState
    decision_id: str | None = None
    history: list[tuple[str, str, str | None]] = field(default_factory=list)

    def transition(self, target: CandidateState, *, decision_id: str | None = None) -> None:
        if target not in CANDIDATE_TRANSITIONS.get(self.state, set()):
            raise ValueError(f"invalid transition {self.state}->{target}")
        if target in {
            CandidateState.SELECTED,
            CandidateState.DEFERRED,
            CandidateState.DROPPED,
            CandidateState.EXPAND_SELECTED,
            CandidateState.FULL_SCAN_SELECTED,
            CandidateState.DEEP_TEST_SELECTED,
            CandidateState.MONITOR_SELECTED,
        } and not decision_id:
            raise ValueError("semantic candidate transitions require an AI decision id")
        self.history.append((self.state.value, target.value, decision_id))
        self.state = target
        if decision_id:
            self.decision_id = decision_id


@dataclass
class DecisionLifecycle:
    state: DecisionState = DecisionState.REQUESTED

    def transition(self, target: DecisionState) -> None:
        if target not in DECISION_TRANSITIONS.get(self.state, set()) and target not in {
            DecisionState.SUPERSEDED,
            DecisionState.CANCELLED,
            DecisionState.DECISION_BLOCKED,
            DecisionState.INVALID_OUTPUT,
        }:
            raise ValueError(f"invalid decision transition {self.state}->{target}")
        self.state = target


@dataclass
class SegmentLifecycle:
    state: SegmentState = SegmentState.CREATED

    def transition(self, target: SegmentState) -> None:
        if target not in SEGMENT_TRANSITIONS.get(self.state, set()):
            raise ValueError(f"invalid segment transition {self.state}->{target}")
        self.state = target
