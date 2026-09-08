from proxy_pipeline.queue.spool import AppendOnlySpool
from proxy_pipeline.state import CandidateState, StateMachine


def test_candidate_state_machine_rejects_skip():
    machine = StateMachine(CandidateState.DISCOVERED)
    try:
        machine.transition(CandidateState.SCANNING)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid transition accepted")


def test_semantic_transition_requires_decision_id():
    machine = StateMachine(CandidateState.DECISION_PENDING)
    try:
        machine.transition(CandidateState.SELECTED)
    except ValueError:
        pass
    else:
        raise AssertionError("semantic transition without decision id accepted")
    machine.transition(CandidateState.SELECTED, decision_id="d-1")
    assert machine.state is CandidateState.SELECTED
    assert machine.decision_id == "d-1"


def test_spool_is_append_only(tmp_path):
    spool = AppendOnlySpool(tmp_path / "events.log")
    spool.append("one")
    spool.append("two")
    assert [line for _, line in spool.read_from()] == ["one", "two"]
