"""VDS üzerinde kalıcı ajan/job/event state deposu."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any

from services.agentd.protocol import make_event, new_id, redact

PET_NAMES = ("Atlas", "Pus", "Kor", "Mavi", "Tosba", "Kivilcim", "Golge", "Firtina")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class StateStore:
    EVENT_MEMORY_LIMIT = 5000

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.agents_dir = self.root / "agents"
        self.agents_file = self.root / "agents.json"
        self.events_file = self.root / "events.jsonl"
        self._lock = threading.RLock()
        self._agents: dict[str, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self._event_ids: set[str] = set()
        self._next_seq = 1
        self.root.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self._chmod_private(self.root)
        self._chmod_private(self.agents_dir)
        self._load_agents()
        corruption = self._load_events()
        if corruption:
            self.record_event(
                "state_corruption",
                state="unknown",
                error=corruption,
                working_note="Event deposunda bozuk bir satır bulundu; geçerli geçmiş korunarak devam ediyorum.",
            )

    @staticmethod
    def _chmod_private(path: Path) -> None:
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass

    def _load_agents(self) -> None:
        try:
            payload = json.loads(self.agents_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(payload, dict):
            self._agents = {
                str(agent_id): dict(agent)
                for agent_id, agent in payload.items()
                if isinstance(agent, dict)
            }
            for agent in self._agents.values():
                if agent.get("last_video_ref") and not agent.get("last_video_provenance_ref"):
                    agent["last_video_ref"] = None

    def _load_events(self) -> str | None:
        corruption: str | None = None
        try:
            handle = self.events_file.open("r", encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            return f"events file could not be read: {type(exc).__name__}"
        with handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError("event is not an object")
                    seq = int(event.get("seq", 0) or 0)
                    if seq > 0:
                        self._events.append(event)
                        event_id = str(event.get("event_id", "") or "")
                        if event_id:
                            self._event_ids.add(event_id)
                        self._next_seq = max(self._next_seq, seq + 1)
                except (ValueError, TypeError, json.JSONDecodeError):
                    corruption = corruption or f"events line {line_number} is invalid"
        self._events.sort(key=lambda event: int(event.get("seq", 0) or 0))
        # The full history stays on disk; memory keeps only the newest window so a
        # multi-hundred-megabyte event log cannot pin the whole VDS in RSS.
        if len(self._events) > self.EVENT_MEMORY_LIMIT:
            kept = self._events[-self.EVENT_MEMORY_LIMIT:]
            self._events = kept
            self._event_ids = {
                str(event.get("event_id", "") or "")
                for event in kept
                if str(event.get("event_id", "") or "")
            }
        return corruption

    def _write_agents(self) -> None:
        temporary = self.agents_file.with_suffix(".json.tmp")
        data = json.dumps(self._agents, ensure_ascii=False, indent=2)
        temporary.write_text(data + "\n", encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, self.agents_file)
        try:
            os.chmod(self.agents_file, 0o600)
        except OSError:
            pass

    def _write_manifest(self, agent_id: str) -> None:
        agent = self._agents.get(agent_id)
        if not agent:
            return
        agent_dir = self.agents_dir / agent_id
        (agent_dir / "frames").mkdir(parents=True, exist_ok=True)
        (agent_dir / "video").mkdir(parents=True, exist_ok=True)
        self._chmod_private(agent_dir)
        payload = json.dumps(agent, ensure_ascii=False, indent=2)
        temporary = agent_dir / "manifest.json.tmp"
        temporary.write_text(payload + "\n", encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, agent_dir / "manifest.json")

    def create_agent(self, kind: str, label: str, pet_name: str | None = None, initial_input: str = "") -> dict[str, Any]:
        with self._lock:
            agent_id = new_id("ajan")
            job_id = new_id("is")
            index = len(self._agents) % len(PET_NAMES)
            pet = {
                "name": pet_name.strip() if pet_name and pet_name.strip() else f"{PET_NAMES[index]}-{agent_id[-4:]}",
                "mood": "meraklı",
                "energy": 100,
                "last_event_seq": 0,
            }
            now = utc_now()
            agent = {
                "agent_id": agent_id,
                "job_id": job_id,
                "kind": str(kind or "gezinme"),
                "label": str(label or kind or "uzak ajan"),
                "initial_input": str(initial_input or "")[:2000],
                "state": "created",
                "pet": pet,
                "pid": None,
                "process_group": None,
                "current_target": "",
                "working_note": "VDS ajanı oluşturuldu; başlatılmayı bekliyor.",
                "hypothesis": "",
                "counter_hypothesis": "",
                "next_action": "operator start",
                "last_seq": 0,
                "last_frame_ref": None,
                "last_frame_provenance_ref": None,
                "last_frame_event_id": None,
                "last_frame_render_revision": None,
                "last_video_ref": None,
                "last_video_provenance_ref": None,
                "capture_kind": "sway-headless",
                "display_capability": {},
                "wayvnc_stream_ref": None,
                "display_control": {},
                "last_output_ref": None,
                "last_evidence_refs": [],
                "last_decision": None,
                "last_result_summary": None,
                "operator_directives": [],
                "published_proxies": [],
                "visible": True,
                "created_at": now,
                "updated_at": now,
                "event_history": [],
            }
            self._agents[agent_id] = agent
            self._write_agents()
            self._write_manifest(agent_id)
            self.record_event(
                "agent_created",
                agent_id=agent_id,
                job_id=job_id,
                state="created",
                working_note="VDS üzerinde yeni ajan kaydı oluşturuldu.",
                next_action="operator start",
            )
            return dict(self._agents[agent_id])

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            agent = self._agents.get(agent_id)
            return dict(agent) if agent else None

    def list_agents(self, include_hidden: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            values = self._agents.values()
            if not include_hidden:
                values = (agent for agent in values if agent.get("visible", True))
            return [dict(agent) for agent in values]

    def update_agent(self, agent_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                raise KeyError(agent_id)
            agent.update(redact(fields))
            agent["updated_at"] = utc_now()
            self._write_agents()
            self._write_manifest(agent_id)
            return dict(agent)

    def append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            payload = dict(redact(event))
            payload["kind"] = "event"
            event_id = str(payload.get("event_id", "") or "")
            if event_id and event_id in self._event_ids:
                for existing in reversed(self._events):
                    if str(existing.get("event_id", "") or "") == event_id:
                        return dict(existing)
            payload["seq"] = self._next_seq
            self._next_seq += 1
            self._events.append(payload)
            if event_id:
                self._event_ids.add(event_id)
            if len(self._events) > self.EVENT_MEMORY_LIMIT:
                dropped = self._events[:-self.EVENT_MEMORY_LIMIT]
                self._events = self._events[-self.EVENT_MEMORY_LIMIT:]
                for old in dropped:
                    old_id = str(old.get("event_id", "") or "")
                    if old_id:
                        self._event_ids.discard(old_id)
            with self.events_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            agent_id = str(payload.get("agent_id", "") or "")
            agent = self._agents.get(agent_id)
            if agent:
                evidence_only = payload.get("event_type") in {
                    "frame_captured",
                    "video_segment_finalized",
                    "video_recording_finalized",
                    "evidence_capture_unavailable",
                    "evidence_completion_pump_error",
                    "video_capture_unavailable",
                    "evidence_lease_revoke_timeout",
                }
                for field_name, event_name in (
                    ("state", "state"),
                    ("pid", "pid"),
                    ("process_group", "process_group"),
                    ("current_target", "target"),
                    ("working_note", "working_note"),
                    ("hypothesis", "hypothesis"),
                    ("counter_hypothesis", "counter_hypothesis"),
                    ("next_action", "next_action"),
                    ("capture_kind", "capture_kind"),
                    ("display_capability", "display_capability"),
                    ("wayvnc_stream_ref", "wayvnc_stream_ref"),
                    ("display_control", "display_control"),
                ):
                    if evidence_only and field_name in {
                        "state",
                        "pid",
                        "process_group",
                        "current_target",
                        "working_note",
                        "hypothesis",
                        "counter_hypothesis",
                        "next_action",
                    }:
                        continue
                    if event_name in payload and payload[event_name] not in (None, ""):
                        agent[field_name] = payload[event_name]
                for field_name, event_name in (
                    ("last_frame_ref", "frame_ref"),
                    ("last_output_ref", "output_ref"),
                    ("last_decision", "decision"),
                    ("last_result_summary", "result_summary"),
                    ("last_frame_provenance_ref", "frame_provenance_ref"),
                    ("last_frame_event_id", "frame_event_id"),
                    ("last_frame_render_revision", "frame_render_revision"),
                ):
                    if event_name in payload and payload[event_name] not in (None, ""):
                        agent[field_name] = payload[event_name]
                if payload.get("event_type") in {"video_segment_finalized", "video_recording_finalized"}:
                    for field_name, event_name in (
                        ("last_video_ref", "video_ref"),
                        ("last_video_provenance_ref", "video_provenance_ref"),
                    ):
                        if event_name in payload and payload[event_name] not in (None, ""):
                            agent[field_name] = payload[event_name]
                if payload.get("evidence_refs"):
                    agent["last_evidence_refs"] = list(payload["evidence_refs"])[-12:]
                if payload.get("event_type") == "operator_intervention" and payload.get("directive"):
                    directives = list(agent.get("operator_directives", []))
                    intervention_id = payload["directive"].get("intervention_id")
                    if not directives or directives[-1].get("intervention_id") != intervention_id:
                        directives.append(payload["directive"])
                    agent["operator_directives"] = directives[-100:]
                if payload.get("event_type") == "proxy_published":
                    candidate = payload.get("proxy")
                    if not candidate and isinstance(payload.get("result_summary"), dict):
                        candidate = payload["result_summary"].get("candidate")
                    if isinstance(candidate, dict):
                        published = dict(candidate)
                        published["source_event_seq"] = payload["seq"]
                        published["source_event_id"] = payload.get("event_id")
                        published["source_evidence_refs"] = list(payload.get("evidence_refs", []) or [])
                        identity = (
                            published.get("host"),
                            published.get("port"),
                            published.get("protocol"),
                            published.get("validation_ref"),
                        )
                        previous = list(agent.get("published_proxies", []))
                        if not any(
                            (
                                item.get("host"),
                                item.get("port"),
                                item.get("protocol"),
                                item.get("validation_ref"),
                            ) == identity
                            for item in previous
                        ):
                            previous.append(published)
                        agent["published_proxies"] = previous[-500:]
                agent["last_seq"] = payload["seq"]
                history = list(agent.get("event_history", []))
                history.append(payload)
                agent["event_history"] = history[-100:]
                pet = dict(agent.get("pet", {}))
                pet["last_event_seq"] = payload["seq"]
                agent["pet"] = pet
                agent["updated_at"] = utc_now()
                self._write_agents()
                self._write_manifest(agent_id)
            return dict(payload)

    def append_operator_directive(
        self,
        agent_id: str,
        instruction: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                raise KeyError(agent_id)
            cleaned = str(instruction or "").strip()
            if not cleaned:
                raise ValueError("operator instruction is empty")
            directive = {
                "intervention_id": new_id("intervention"),
                "agent_id": agent_id,
                "instruction": cleaned[:2000],
                "created_at": utc_now(),
            }
            if isinstance(context, dict) and context:
                directive["context"] = redact(context)
            path = self.agents_dir / agent_id / "operator-directives.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(directive, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            directives = list(agent.get("operator_directives", []))
            directives.append(directive)
            agent["operator_directives"] = directives[-100:]
            agent["updated_at"] = utc_now()
            self._write_agents()
            self._write_manifest(agent_id)
            return dict(directive)

    def record_event(self, event_type: str, **fields: Any) -> dict[str, Any]:
        return self.append_event(make_event(event_type, **fields))

    def events_after(self, seq: int = 0, agent_id: str | None = None) -> list[dict[str, Any]]:
        threshold = int(seq)
        with self._lock:
            in_memory = [
                dict(event)
                for event in self._events
                if int(event.get("seq", 0) or 0) > threshold
                and (agent_id is None or event.get("agent_id") == agent_id)
            ]
            oldest_in_memory = (
                int(self._events[0].get("seq", 0) or 0) if self._events else None
            )
        # When the caller asks for history older than the in-memory window, replay
        # it from the append-only log instead of pretending it no longer exists.
        if oldest_in_memory is None or threshold + 1 >= oldest_in_memory:
            return in_memory
        from_disk: list[dict[str, Any]] = []
        try:
            with self.events_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    event_seq = int(event.get("seq", 0) or 0)
                    if event_seq <= threshold or event_seq >= oldest_in_memory:
                        continue
                    if agent_id is not None and event.get("agent_id") != agent_id:
                        continue
                    from_disk.append(event)
        except OSError:
            return in_memory
        from_disk.sort(key=lambda event: int(event.get("seq", 0) or 0))
        return from_disk + in_memory

    def remove_agent(self, agent_id: str) -> dict[str, Any]:
        with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                raise KeyError(agent_id)
            agent["visible"] = False
            agent["state"] = "destroyed"
            agent["updated_at"] = utc_now()
            self._write_agents()
            self._write_manifest(agent_id)
            return dict(agent)

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._next_seq - 1


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory(prefix="paidproxy-agentd-") as directory:
        store = StateStore(Path(directory))
        agent = store.create_agent("gezinme", "state-demo")
        print(json.dumps(agent, ensure_ascii=False))
        print(json.dumps(store.events_after(), ensure_ascii=False))
