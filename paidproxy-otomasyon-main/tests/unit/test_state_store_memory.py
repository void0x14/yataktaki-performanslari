import json
from pathlib import Path
from services.agentd.state import StateStore


def test_state_store_bounds_in_memory_events(tmp_path):
    root = tmp_path / "agentd"
    root.mkdir()
    events = root / "events.jsonl"
    with events.open("w", encoding="utf-8") as h:
        for i in range(1, 5001):
            h.write(json.dumps({"kind": "event", "seq": i, "agent_id": "a1", "event_type": "x"}) + "\n")
    store = StateStore(root)
    assert len(store._events) <= store.EVENT_MEMORY_LIMIT
    assert store._next_seq == 5001


def test_state_store_event_lookup_is_not_linear_scan(tmp_path):
    root = tmp_path / "agentd"
    store = StateStore(root)
    for _ in range(50):
        store.record_event("probe", agent_id="a1")
    # duplicate detection must use an index, not scan the whole list
    assert isinstance(store._event_ids, (set, dict))
    assert len(store._event_ids) == 50


def test_events_after_reads_from_disk_beyond_memory_window(tmp_path):
    root = tmp_path / "agentd"
    store = StateStore(root)
    first = store.record_event("a", agent_id="a1")
    for _ in range(store.EVENT_MEMORY_LIMIT + 20):
        store.record_event("b", agent_id="a1")
    got = store.events_after(0, "a1")
    assert len(got) >= store.EVENT_MEMORY_LIMIT + 21
    assert got[0]["seq"] == first["seq"]


def test_event_load_never_accumulates_full_history_in_memory(tmp_path):
    """Peak memory must stay bounded: the loader may not build a list of every
    historical event before trimming to the window."""
    root = tmp_path / "agentd"
    root.mkdir()
    events = root / "events.jsonl"
    total = 20000
    with events.open("w", encoding="utf-8") as h:
        for i in range(1, total + 1):
            h.write(json.dumps({"kind": "event", "seq": i, "agent_id": "a1"}) + "\n")
    store = StateStore(root)
    assert len(store._events) == store.EVENT_MEMORY_LIMIT
    assert store._next_seq == total + 1
    assert int(store._events[0]["seq"]) == total - store.EVENT_MEMORY_LIMIT + 1
