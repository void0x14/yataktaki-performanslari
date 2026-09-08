from __future__ import annotations

from enum import StrEnum


class CandidateState(StrEnum):
    DISCOVERED = "DISCOVERED"
    CONTEXT_READY = "CONTEXT_READY"
    DECISION_PENDING = "DECISION_PENDING"
    SELECTED = "SELECTED"
    DEFERRED = "DEFERRED"
    DROPPED = "DROPPED"
    MANIFEST_READY = "MANIFEST_READY"
    SAMPLING = "SAMPLING"
    SCANNING = "SCANNING"
    EVIDENCE_READY = "EVIDENCE_READY"
    REASSESSMENT_PENDING = "REASSESSMENT_PENDING"
    EXPAND_SELECTED = "EXPAND_SELECTED"
    FULL_SCAN_SELECTED = "FULL_SCAN_SELECTED"
    DEEP_TEST_SELECTED = "DEEP_TEST_SELECTED"
    MONITOR_SELECTED = "MONITOR_SELECTED"


class DecisionState(StrEnum):
    REQUESTED = "REQUESTED"
    CONTEXT_READY = "CONTEXT_READY"
    INFERENCE_RUNNING = "INFERENCE_RUNNING"
    VALIDATED = "VALIDATED"
    COMMITTED = "COMMITTED"
    EXECUTED = "EXECUTED"
    OUTCOME_ATTACHED = "OUTCOME_ATTACHED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    DECISION_BLOCKED = "DECISION_BLOCKED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class SegmentState(StrEnum):
    CREATED = "CREATED"
    READY = "READY"
    LEASED = "LEASED"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"


class EndpointState(StrEnum):
    L4_OPEN = "L4_OPEN"
    L7_PENDING = "L7_PENDING"
    VALIDATED = "VALIDATED"
    PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    TIMEOUT = "TIMEOUT"
    UNREACHABLE = "UNREACHABLE"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    INACTIVE = "INACTIVE"


CANDIDATE_TRANSITIONS = {
    CandidateState.DISCOVERED: {CandidateState.CONTEXT_READY},
    CandidateState.CONTEXT_READY: {CandidateState.DECISION_PENDING},
    CandidateState.DECISION_PENDING: {
        CandidateState.SELECTED,
        CandidateState.DEFERRED,
        CandidateState.DROPPED,
    },
    CandidateState.SELECTED: {CandidateState.MANIFEST_READY},
    CandidateState.MANIFEST_READY: {CandidateState.SAMPLING, CandidateState.SCANNING},
    CandidateState.SAMPLING: {CandidateState.EVIDENCE_READY},
    CandidateState.SCANNING: {CandidateState.EVIDENCE_READY},
    CandidateState.EVIDENCE_READY: {CandidateState.REASSESSMENT_PENDING},
    CandidateState.REASSESSMENT_PENDING: {
        CandidateState.SELECTED,
        CandidateState.DEFERRED,
        CandidateState.DROPPED,
        CandidateState.EXPAND_SELECTED,
        CandidateState.FULL_SCAN_SELECTED,
        CandidateState.DEEP_TEST_SELECTED,
        CandidateState.MONITOR_SELECTED,
    },
    CandidateState.EXPAND_SELECTED: {CandidateState.MANIFEST_READY},
    CandidateState.FULL_SCAN_SELECTED: {CandidateState.MANIFEST_READY},
    CandidateState.DEEP_TEST_SELECTED: {CandidateState.MANIFEST_READY},
    CandidateState.MONITOR_SELECTED: {CandidateState.DEFERRED},
}

DECISION_TRANSITIONS = {
    DecisionState.REQUESTED: {DecisionState.CONTEXT_READY, DecisionState.CANCELLED, DecisionState.DECISION_BLOCKED},
    DecisionState.CONTEXT_READY: {DecisionState.INFERENCE_RUNNING, DecisionState.CANCELLED, DecisionState.DECISION_BLOCKED},
    DecisionState.INFERENCE_RUNNING: {
        DecisionState.VALIDATED,
        DecisionState.INVALID_OUTPUT,
        DecisionState.DECISION_BLOCKED,
        DecisionState.CANCELLED,
    },
    DecisionState.VALIDATED: {DecisionState.COMMITTED, DecisionState.CANCELLED},
    DecisionState.COMMITTED: {DecisionState.EXECUTED, DecisionState.SUPERSEDED, DecisionState.CANCELLED},
    DecisionState.EXECUTED: {DecisionState.OUTCOME_ATTACHED},
    DecisionState.INVALID_OUTPUT: {DecisionState.REQUESTED, DecisionState.CANCELLED, DecisionState.DECISION_BLOCKED},
}

SEGMENT_TRANSITIONS = {
    SegmentState.CREATED: {SegmentState.READY, SegmentState.FAILED},
    SegmentState.READY: {SegmentState.LEASED, SegmentState.FAILED},
    SegmentState.LEASED: {SegmentState.PARTIAL, SegmentState.COMPLETED, SegmentState.FAILED, SegmentState.READY},
    SegmentState.PARTIAL: {SegmentState.LEASED, SegmentState.COMPLETED, SegmentState.FAILED},
    SegmentState.COMPLETED: {SegmentState.ARCHIVED},
}
