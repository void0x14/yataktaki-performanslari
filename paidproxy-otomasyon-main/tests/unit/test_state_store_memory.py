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
