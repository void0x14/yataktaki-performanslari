"""paidproxy-agentd JSONL komut/event sözleşmesi.

Bu modül operasyon kararlarını değil, yalnızca süreçler arası görünür sözleşmeyi
tanımlar. VDS'de çalışır; yerel masaüstü aynı sözleşmenin istemcisidir.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any
from uuid import uuid4

COMMANDS = (
    "status",
    "create",
    "start",
    "pause",
    "resume",
    "hard_kill",
    "intervene",
    "destroy",
    "subscribe",
    "replay",
    "viewport",
    "display_select",
    "display_release",
)

TERMINAL_STATES = frozenset({"killed", "destroyed", "completed", "failed"})
ACTIVE_STATES = frozenset({"created", "running", "paused", "recovering", "unknown"})
SENSITIVE_KEY_PARTS = (
    "authorization",
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
    "api_key",
)
SECRET_VALUE_RE = re.compile(r"(?i)bearer\\s+[A-Za-z0-9._~+/=-]+")
LOCAL_SECRET_PATH_RE = re.compile(r"(?i)(?:/home/[^\\s/]+)?/\\.ssh/[^\\s]+|[A-Za-z]:\\\\Users\\\\[^\\s]+")
MAX_EVENT_TEXT = 4000


class ProtocolError(ValueError):
    """Bir komut/event mesajı sözleşmeye uymadığında kullanılır."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:16]}"


def _redact_string(value: str) -> str:
    value = SECRET_VALUE_RE.sub("Bearer [REDACTED]", value)
    value = LOCAL_SECRET_PATH_RE.sub("[REDACTED_PATH]", value)
    return value[:MAX_EVENT_TEXT]


def redact(value: Any, key: str = "") -> Any:
    """Event ve komut payload'ındaki sırları tekrar tekrar ve derinlemesine temizler."""
    lowered = key.lower()
    if any(part in lowered for part in SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, key) for v in value]
    return value


def encode_message(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise ProtocolError("JSONL message must be an object")
    return json.dumps(redact(payload), ensure_ascii=False, separators=(",", ":")) + "\n"


def decode_message(line: str | bytes) -> dict[str, Any]:
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    try:
        payload = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"invalid JSONL message: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProtocolError("JSONL message must be an object")
    return payload


def make_command(command: str, request_id: str | None = None, **payload: Any) -> dict[str, Any]:
    if command not in COMMANDS:
        raise ProtocolError(f"unknown command: {command}")
    return {
        "kind": "command",
        "request_id": request_id or new_id("request"),
        "command": command,
        **redact(payload),
    }


def make_event(
    event_type: str,
    *,
    agent_id: str = "",
    job_id: str = "",
    pid: int | None = None,
    process_group: int | None = None,
    state: str = "unknown",
    tool: str = "",
    target: str = "",
    working_note: str = "",
    hypothesis: str = "",
    counter_hypothesis: str = "",
    evidence_refs: list[str] | None = None,
    decision: Any = None,
    next_action: str = "",
    output_ref: str | None = None,
    frame_ref: str | None = None,
    video_ref: str | None = None,
    render_revision: str | None = None,
    frame_provenance_ref: str | None = None,
    frame_event_id: str | None = None,
    frame_render_revision: str | None = None,
    video_provenance_ref: str | None = None,
    capture_kind: str = "",
    display_capability: Any = None,
    wayvnc_stream_ref: str | None = None,
    display_control: Any = None,
    operator_action: str | None = None,
    error: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "kind": "event",
        "event_id": new_id("event"),
        "seq": None,
        "timestamp": now_utc(),
        "agent_id": agent_id,
        "job_id": job_id,
        "pid": pid,
        "process_group": process_group,
        "state": state,
        "event_type": event_type,
        "tool": tool,
        "target": target,
        "working_note": working_note,
        "hypothesis": hypothesis,
        "counter_hypothesis": counter_hypothesis,
        "evidence_refs": list(evidence_refs or []),
        "decision": decision,
        "next_action": next_action,
        "output_ref": output_ref,
        "frame_ref": frame_ref,
        "video_ref": video_ref,
        "render_revision": render_revision,
        "frame_provenance_ref": frame_provenance_ref,
        "frame_event_id": frame_event_id,
        "frame_render_revision": frame_render_revision,
        "video_provenance_ref": video_provenance_ref,
        "capture_kind": capture_kind,
        "display_capability": display_capability,
        "wayvnc_stream_ref": wayvnc_stream_ref,
        "display_control": display_control,
        "operator_action": operator_action,
        "error": error,
        **extra,
    }
    return redact(payload)


def error_response(request_id: str | None, error: str, detail: str = "") -> dict[str, Any]:
    return {
        "kind": "response",
        "request_id": request_id or "",
        "ok": False,
        "error": error,
        "detail": _redact_string(detail),
    }


def ok_response(request_id: str | None, **payload: Any) -> dict[str, Any]:
    return {"kind": "response", "request_id": request_id or "", "ok": True, **redact(payload)}


if __name__ == "__main__":
    print(encode_message(make_command("status", "protocol-demo")))
    print(encode_message(make_event(
        "protocol_demo",
        agent_id="ajan-demo",
        working_note="Sözleşme görünür biçimde hazır",
        evidence_refs=["vds://agentd/demo"],
    )), end="")
