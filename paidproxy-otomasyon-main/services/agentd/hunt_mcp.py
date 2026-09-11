#!/usr/bin/env python3
"""paidproxy hunt MCP server (stdio, JSON-RPC 2.0).

This server exposes the real VDS hunt tool handlers that already live in
``services.agentd.ai_runtime`` over the Model Context Protocol. It contains no
hunting logic and no decision harness: every ``tools/call`` is routed to the
existing ``ToolCatalog.invoke()`` of a tool-only ``AgentRuntime``.

Transport: newline-delimited JSON-RPC 2.0 on stdin/stdout.
stdout carries protocol frames only; all diagnostics go to stderr.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import traceback
from typing import Any

SERVER_NAME = "paidproxy-hunt"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
MAX_TOOL_TEXT = 120_000

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Reserve the real stdout for protocol frames. Any accidental library print
# then lands on stderr instead of corrupting the MCP channel.
_PROTOCOL_OUT = sys.stdout
sys.stdout = sys.stderr

_MODULE: Any | None = None
_RUNTIME: Any | None = None
_TOOLS: list[dict[str, Any]] | None = None

_PROTOCOLS = ["http_connect", "socks5", "socks4", "socks4a"]

_FIELD_SCHEMA: dict[str, dict[str, Any]] = {
    "url": {"type": "string", "description": "Absolute public http/https URL."},
    "timeout": {"type": "number", "minimum": 0, "description": "Seconds."},
    "ip": {"type": "string", "description": "IPv4 address."},
    "host": {"type": "string", "description": "Proxy host or IPv4 address."},
    "asn": {"type": "string", "description": "Autonomous system number, e.g. AS8075."},
    "cidr": {"type": "string", "description": "IPv4 CIDR block to scan."},
    "rate": {"type": "integer", "minimum": 50, "maximum": 1000000},
    "concurrency": {"type": "integer", "minimum": 1, "maximum": 1024},
    "port_range": {"type": "string", "description": "Port range such as 1-65535."},
    "port_spec": {"type": "string", "description": "Comma/range port spec."},
    "ports": {
        "type": "array",
        "items": {"type": "integer", "minimum": 1, "maximum": 65535},
    },
    "port": {"type": "integer", "minimum": 1, "maximum": 65535},
    "target_url": {
        "type": "string",
        "description": "Absolute public http/https URL used for egress proof.",
    },
    "protocols": {
        "type": "array",
        "items": {"type": "string", "enum": _PROTOCOLS},
        "minItems": 1,
    },
    "protocol": {"type": "string", "enum": _PROTOCOLS},
    "validation_ref": {
        "type": "string",
        "description": "agent:// artifact reference returned by validate_proxy.",
    },
    "quality_label": {"type": "string"},
    "quality_rationale": {"type": "string"},
    "evidence": {"type": "array", "items": {"type": "string"}},
}


def _stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _load_module() -> Any:
    global _MODULE
    if _MODULE is None:
        from services.agentd import ai_runtime  # noqa: PLC0415

        _MODULE = ai_runtime
    return _MODULE


def _agent_root() -> Path:
    configured = os.environ.get("PAIDPROXY_AGENTD_ROOT")
    root = Path(configured).expanduser() if configured else _REPO_ROOT / "var" / "agentd"
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _make_emit(event_path: Path):
    def emit(event_type: str, message: str = "", **fields: Any) -> None:
        record = {
            "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": str(event_type),
            "message": str(message),
            **fields,
        }
        try:
            event_path.parent.mkdir(parents=True, exist_ok=True)
            with event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            pass
        if os.environ.get("PAIDPROXY_MCP_DEBUG") == "1":
            _stderr("paidproxy-hunt event: " + json.dumps(record, ensure_ascii=False)[:2000])

    return emit


def _get_runtime() -> Any:
    global _RUNTIME
    if _RUNTIME is None:
        module = _load_module()
        root = _agent_root()
        agent_id = os.environ.get("PAIDPROXY_HUNT_AGENT_ID") or "claude-hunt"
        job_id = os.environ.get("PAIDPROXY_HUNT_JOB_ID") or f"mcp-{os.getpid()}"
        emit = _make_emit(root / "agents" / agent_id / "events.jsonl")
        _RUNTIME = module.AgentRuntime(
            root=root,
            agent_id=agent_id,
            job_id=job_id,
            kind="hunt",
            initial_input="",
            emit=emit,
            stopped=lambda: False,
        )
    return _RUNTIME


def _composite_fields(token: str) -> list[str]:
    found: list[str] = []
    for field in _FIELD_SCHEMA:
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(field)}(?![A-Za-z0-9_])", token):
            found.append(field)
    # The operator phrasing "first port in ports" / "port_spec/port_range"
    # mentions the generic word "port"; drop it when a specific key matched.
    if any(name in found for name in ("ports", "port_spec", "port_range")):
        found = [field for field in found if field != "port"]
    return found


def _schema_for(contract: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    any_of: list[dict[str, Any]] = []

    for group in ("required", "optional"):
        for raw in contract.get(group, []) or []:
            token = str(raw).strip()
            if not token:
                continue
            if token in _FIELD_SCHEMA:
                properties[token] = dict(_FIELD_SCHEMA[token])
                if group == "required":
                    required.append(token)
                continue
            if " OR " in token:
                alternatives: list[dict[str, Any]] = []
                for part in token.split(" OR "):
                    for name in _composite_fields(part):
                        properties[name] = dict(_FIELD_SCHEMA[name])
                        alternatives.append({"required": [name]})
                if alternatives:
                    any_of.append({"anyOf": alternatives})

    # Handler-supported optional extras that the raw contract mentions as notes.
    for extra in ("evidence",):
        if extra in _FIELD_SCHEMA and extra not in properties and contract.get(extra):
            properties[extra] = dict(_FIELD_SCHEMA[extra])

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    if any_of:
        schema["allOf"] = any_of
    return schema


def _annotations(capabilities: list[str]) -> dict[str, Any]:
    caps = set(capabilities or [])
    return {
        "readOnlyHint": "read_only" in caps,
        "destructiveHint": False,
        "idempotentHint": "read_only" in caps,
        "openWorldHint": bool({"internet", "rdap", "routing", "network"} & caps),
    }


def _tool_definitions() -> list[dict[str, Any]]:
    global _TOOLS
    if _TOOLS is None:
        module = _load_module()
        runtime = _get_runtime()
        contracts = getattr(module, "ARGUMENT_CONTRACTS", {})
        tools: list[dict[str, Any]] = []
        for item in runtime.catalog.describe():
            name = str(item.get("name") or "")
            contract = dict(contracts.get(name) or item.get("arguments") or {})
            tools.append(
                {
                    "name": name,
                    "description": str(item.get("description") or name),
                    "inputSchema": _schema_for(contract),
                    "annotations": _annotations(item.get("capabilities") or []),
                }
            )
        _TOOLS = tools
    return _TOOLS


def _tool_text(payload: Any) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    if len(text) > MAX_TOOL_TEXT:
        text = text[:MAX_TOOL_TEXT] + f"\n... [truncated at {MAX_TOOL_TEXT} chars]"
    return text


def _call_tool(name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    known = {tool["name"] for tool in _tool_definitions()}
    if name not in known:
        return f"unknown tool: {name}; known: {', '.join(sorted(known))}", True
    runtime = _get_runtime()
    try:
        runtime.step = int(getattr(runtime, "step", 0)) + 1
        with redirect_stdout(sys.stderr):
            result = runtime.catalog.invoke(name, dict(arguments or {}))
        return _tool_text(result), False
    except Exception as exc:  # noqa: BLE001 - must never kill the MCP loop
        _stderr("paidproxy-hunt tool error: " + "".join(traceback.format_exception(exc))[-4000:])
        return f"{type(exc).__name__}: {exc}", True


def _send(message: dict[str, Any]) -> None:
    _PROTOCOL_OUT.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    _PROTOCOL_OUT.flush()


def _result(request_id: Any, result: dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: Any, code: int, message: str, data: Any = None) -> None:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = data
    _send({"jsonrpc": "2.0", "id": request_id, "error": payload})


def _handle(message: dict[str, Any]) -> None:
    request_id = message.get("id")
    method = str(message.get("method") or "")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    is_notification = "id" not in message

    if method == "initialize":
        protocol = str(params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION)
        _result(
            request_id,
            {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Real VDS proxy-hunt tools. inspect_owner_context and "
                    "list_owner_ranges read ownership; masscan_liveness does L4; "
                    "port_scan_live_ip enumerates every open port; validate_proxy "
                    "proves L7 + real egress; publish_proxy only accepts proven "
                    "validation_ref artifacts."
                ),
            },
        )
        return

    if method in {"notifications/initialized", "initialized", "notifications/cancelled", "$/cancelRequest"}:
        return

    if method == "ping":
        if not is_notification:
            _result(request_id, {})
        return

    if method == "tools/list":
        _result(request_id, {"tools": _tool_definitions()})
        return

    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        text, failed = _call_tool(name, arguments)
        _result(
            request_id,
            {"content": [{"type": "text", "text": text}], "isError": bool(failed)},
        )
        return

    if is_notification:
        return
    _error(request_id, -32601, f"method not found: {method}")


def main() -> int:
    _stderr(f"{SERVER_NAME} {SERVER_VERSION} ready (repo={_REPO_ROOT})")
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            _error(None, -32700, f"parse error: {exc}")
            continue
        if not isinstance(message, dict):
            _error(None, -32600, "invalid request")
            continue
        try:
            _handle(message)
        except Exception as exc:  # noqa: BLE001 - keep the transport alive
            _stderr("paidproxy-hunt dispatch error: " + "".join(traceback.format_exception(exc))[-4000:])
            if "id" in message:
                _error(message.get("id"), -32603, f"internal error: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
