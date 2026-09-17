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

    cmd = "/home/mani/paidproxy-otomasyon/.venv/bin/python /tmp/harvest/status.py"
    try:
        ret = run_remote(cfg, cmd, timeout=8)
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


def _start_anchor_scan(cfg, payload: dict) -> dict:
    raw_targets = str(payload.get("targets", "")).strip()
    ports = str(payload.get("ports", "10000,30000,8080,3128")).strip() or "10000,30000,8080,3128"
    try:
        rate = int(payload.get("rate", 4000) or 4000)
    except Exception:
        rate = 4000
    rate = max(500, min(100000, rate))

    import base64
    b64 = base64.b64encode(raw_targets.encode("utf-8")).decode("ascii")
    cmd = f"""
mkdir -p /tmp/harvest && cd /tmp/harvest
echo "{b64}" | base64 -d > custom_targets.txt
if [ ! -s custom_targets.txt ]; then
    cat /tmp/av/hedefler.txt cgnat-v4.txt 2>/dev/null | sort -u > custom_targets.txt
fi
sudo -n pkill -9 -f "masscan.*pas1" 2>/dev/null || true
sleep 1
setsid nohup sudo -n masscan $(cat custom_targets.txt | tr '\\n' ' ') -p {ports} --rate {rate} --wait 1 -oL pas1.hits >pas1.log 2>&1 </dev/null &
echo "STARTED"
"""
    try:
        ret = run_remote(cfg, cmd, timeout=12)
        return {"ok": True, "message": f"Çapa taraması VDS'te başlatıldı (Portlar: {ports}, Hız: {rate} pps)"}
    except Exception as exc:
        return {"ok": False, "error": f"Tarama başlatılamadı: {type(exc).__name__}: {exc}"}


def _start_gen_and_check(cfg, payload: dict) -> dict:
    cmd = """
cd /tmp/harvest || exit 1
awk '$1=="open"{print $4}' pas1.hits 2>/dev/null | sort -u > live_ips.txt
TOTAL_IPS=$(wc -l < live_ips.txt 2>/dev/null || echo 0)
pkill -f stream_validator 2>/dev/null || true
sleep 1
nohup ./stream_validator.sh > validator.log 2>&1 &
echo "STARTED $TOTAL_IPS"
"""
    try:
        ret = run_remote(cfg, cmd, timeout=10)
        return {"ok": True, "message": f"Doğrulayıcı başlatıldı ({ret.stdout.strip()})"}
    except Exception as exc:
        return {"ok": False, "error": f"Doğrulama başlatılamadı: {type(exc).__name__}: {exc}"}


def _stop_all_scans(cfg) -> dict:
    cmd = "sudo -n pkill -9 -f masscan 2>/dev/null; pkill -9 -f stream_validator 2>/dev/null; pkill -9 -f siniflandir 2>/dev/null; echo 'STOPPED'"
    try:
        ret = run_remote(cfg, cmd, timeout=8)
        return {"ok": True, "message": "VDS üzerindeki tüm tarama ve doğrulama süreçleri durduruldu."}
    except Exception as exc:
        return {"ok": False, "error": f"Durdurulamadı: {type(exc).__name__}: {exc}"}


_CLIENT = RemoteAgentClient()


def handle(message: dict) -> dict:
    command = str(message.pop("command"))
    if command == "get_harvest_data":
        return _get_harvest_data(_CLIENT.config, force=bool(message.get("force", False)))
    if command == "start_anchor_scan":
        return _start_anchor_scan(_CLIENT.config, message)
    if command == "start_gen_and_check":
        return _start_gen_and_check(_CLIENT.config, message)
    if command == "stop_all_scans":
        return _stop_all_scans(_CLIENT.config)

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
