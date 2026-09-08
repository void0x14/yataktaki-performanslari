"""Core contracts. No model or agent framework may depend on this package."""

from proxy_pipeline.domain.events import EVENT_TYPES, Event
from proxy_pipeline.domain.models import Action, Decision, DecisionContext, DecisionItem, DecisionState, ExecutionManifest, Target
from proxy_pipeline.domain.states import CandidateState, EndpointState, SegmentState

__all__ = [
    "Action",
    "CandidateState",
    "Decision",
    "DecisionContext",
    "DecisionItem",
    "DecisionState",
    "EndpointState",
    "Event",
    "EVENT_TYPES",
    "ExecutionManifest",
    "SegmentState",
    "Target",
]
