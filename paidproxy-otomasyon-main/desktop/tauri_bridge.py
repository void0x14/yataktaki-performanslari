"""Thin stdin/stdout bridge from Tauri to the existing VDS agentd client."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop.app.agentd_client import RemoteAgentClient


def main() -> int:
    message = json.load(sys.stdin)
    command = str(message.pop("command"))
    client = RemoteAgentClient()
    try:
        response = client.request(command, **message)
        json.dump(response, sys.stdout, ensure_ascii=False)
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
