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

    cmd = "/usr/bin/python3 /home/mani/harvest/status.py"
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
    """Otonom fabrikayı başlat (harvest.service 7/24 döngüsü)."""
    cmd = "sudo -n systemctl start harvest.service 2>&1; sudo -n systemctl is-active harvest.service"
    try:
        ret = run_remote(cfg, cmd, timeout=12)
        durum = ret.stdout.strip().splitlines()[-1] if ret.stdout.strip() else "?"
        return {"ok": True, "message": f"Otonom hasat fabrikası başlatıldı (durum: {durum})"}
    except Exception as exc:
        return {"ok": False, "error": f"Başlatılamadı: {type(exc).__name__}: {exc}"}


def _start_gen_and_check(cfg, payload: dict) -> dict:
    """Döngüyü tazele — harvest.service yeniden başlatılır."""
    cmd = "sudo -n systemctl restart harvest.service 2>&1; sudo -n systemctl is-active harvest.service"
    try:
        ret = run_remote(cfg, cmd, timeout=15)
        durum = ret.stdout.strip().splitlines()[-1] if ret.stdout.strip() else "?"
        return {"ok": True, "message": f"Otonom döngü tazelendi (durum: {durum})"}
    except Exception as exc:
        return {"ok": False, "error": f"Tazelenemedi: {type(exc).__name__}: {exc}"}


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
    cmd = "sudo -n systemctl stop harvest.service 2>/dev/null; sudo -n pkill -9 masscan 2>/dev/null; echo 'STOPPED'"
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
