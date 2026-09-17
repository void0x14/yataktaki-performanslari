"""Thin stdin/stdout bridge from Tauri to the existing VDS agentd client."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cockpit.bridge.agentd_client import RemoteAgentClient
from cockpit.bridge.vds import run_remote

_HARVEST_CACHE: dict = {"ts": 0.0, "data": None}


def _get_harvest_data(cfg, force: bool = False) -> dict:
    now = time.time()
    if not force and _HARVEST_CACHE["data"] is not None and (now - _HARVEST_CACHE["ts"]) < 2.5:
        return _HARVEST_CACHE["data"]

    cmd = """python3 -c "
import os, json
res = {
    'ok': True,
    'open_ports': 0,
    'total_live': 0,
    'v6_count': 0,
    'v4_count': 0,
    'rotate_count': 0,
    'socks_count': 0,
    'connect_count': 0,
    'scan_progress': 'Tamamlandı',
    'proxies': []
}
if os.path.exists('/tmp/harvest/pas1.hits'):
    with open('/tmp/harvest/pas1.hits') as f:
        res['open_ports'] = sum(1 for l in f if l.startswith('open'))
if os.path.exists('/tmp/harvest/pas1.log'):
    with open('/tmp/harvest/pas1.log') as f:
        lines = f.read().splitlines()
        for l in reversed(lines[-30:]):
            if 'rate:' in l:
                res['scan_progress'] = l.strip()
                break
if os.path.exists('/tmp/harvest/validated_pool.txt'):
    with open('/tmp/harvest/validated_pool.txt') as f:
        for line in f:
            p = line.strip().split(maxsplit=5)
            if len(p) >= 5:
                proto = p[1]
                ver = p[2]
                org = p[3]
                rot = p[4]
                egress = p[5] if len(p) > 5 else ''
                res['proxies'].append({
                    'endpoint': p[0],
                    'protocol': proto,
                    'version': ver,
                    'type': org,
                    'rotation': rot,
                    'egress': egress[:60]
                })
                res['total_live'] += 1
                if ver == 'v6': res['v6_count'] += 1
                elif ver == 'v4': res['v4_count'] += 1
                if rot == 'rotate': res['rotate_count'] += 1
                if 'SOCKS' in proto: res['socks_count'] += 1
                if 'CON' in proto: res['connect_count'] += 1
print(json.dumps(res, ensure_ascii=False))
" """
    try:
        ret = run_remote(cfg, cmd, timeout=10)
        data = json.loads(ret.stdout.strip())
        _HARVEST_CACHE["ts"] = now
        _HARVEST_CACHE["data"] = data
        return data
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "open_ports": 0,
            "total_live": 0,
            "v6_count": 0,
            "v4_count": 0,
            "rotate_count": 0,
            "socks_count": 0,
            "connect_count": 0,
            "scan_progress": "Hata",
            "proxies": [],
        }


_CLIENT = RemoteAgentClient()


def handle(message: dict) -> dict:
    command = str(message.pop("command"))
    if command == "get_harvest_data":
        return _get_harvest_data(_CLIENT.config, force=bool(message.get("force", False)))

    slim = bool(message.pop("slim", False))
    response = _CLIENT.request(command, **message)
    # Liste çağrısını hafiflet: event_history replay'den gelir, status'te taşınmaz.
    if slim and command == "status" and isinstance(response.get("agents"), list):
        slim_agents = []
        for agent in response["agents"]:
            if isinstance(agent, dict):
                agent = {k: v for k, v in agent.items() if k != "event_history"}
            slim_agents.append(agent)
        response["agents"] = slim_agents
    return response


def main() -> int:
    loop = "--loop" in sys.argv
    if not loop:
        message = json.load(sys.stdin)
        try:
            json.dump(handle(message), sys.stdout, ensure_ascii=False)
            return 0
        finally:
            _CLIENT.close()
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
    _CLIENT.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
