"""Thin stdin/stdout bridge from Tauri to the existing VDS agentd client."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop.app.agentd_client import RemoteAgentClient


def handle(message: dict) -> dict:
    command = str(message.pop("command"))
    slim = bool(message.pop("slim", False))
    client = handle.client
    response = client.request(command, **message)
    # Liste çağrısını hafiflet: event_history replay'den gelir, status'te taşınmaz.
    if slim and command == "status" and isinstance(response.get("agents"), list):
        slim_agents = []
        for agent in response["agents"]:
            if isinstance(agent, dict):
                agent = {k: v for k, v in agent.items() if k != "event_history"}
            slim_agents.append(agent)
        response["agents"] = slim_agents
    return response


handle.client = RemoteAgentClient()


def main() -> int:
    loop = "--loop" in sys.argv
    if not loop:
        message = json.load(sys.stdin)
        try:
            json.dump(handle(message), sys.stdout, ensure_ascii=False)
            return 0
        finally:
            handle.client.close()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            json.dump(handle(message), sys.stdout, ensure_ascii=False)
        except Exception as exc:
            json.dump({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        sys.stdout.flush()
    handle.client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
