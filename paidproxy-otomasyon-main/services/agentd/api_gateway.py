#!/usr/bin/env python3
"""PaidProxy API Gateway — kokpitin HTTP API katmanı (stdlib-only).

Kokpitin tüm yönetim yüzeylerini HTTP üzerinden açar:

  GET  /api/health                     — agentd + harvest sağlığı
  GET  /api/status                     — ajanların tam durumu (agentd)
  GET  /api/harvest                    — doğrulanmış proxy havuzu + fabrika fazı
  GET  /api/events?agent_id&after_seq&limit — ajan olay akışı (replay)
  POST /api/command                    — {"command": "...", "payload": {...}}
  POST /api/scan/start                 — otonom fabrikayı başlat
  POST /api/scan/stop                  — fabrikayı durdur + masscan temizle
  POST /api/scan/restart               — döngüyü tazele

İzinli komutlar (agentd sözleşmesi):
  status, create, start, pause, resume, hard_kill, intervene, destroy,
  subscribe, replay, viewport, display_select, display_release

Tasarım: agentd JSONL soketine (127.0.0.1:8787) ve harvest dosyalarına
(/home/mani/harvest) köprü kurar. Yalnız loopback'e bağlanır; erişim SSH
üzerinden — agentd ile aynı güven modeli. systemd: paidproxy-api.service
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

AGENTD_HOST = "127.0.0.1"
AGENTD_PORT = 8787
HARVEST_STATUS = Path("/home/mani/harvest/status.py")

COMMANDS = (
    "status", "create", "start", "pause", "resume", "hard_kill",
    "intervene", "destroy", "subscribe", "replay", "viewport",
    "display_select", "display_release",
)

_hstatus = None
if HARVEST_STATUS.exists():
    _spec = importlib.util.spec_from_file_location("harvest_status", str(HARVEST_STATUS))
    if _spec and _spec.loader:
        _hstatus = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_hstatus)


def agentd_call(command: str, payload: dict | None = None, timeout: float = 15.0) -> dict:
    """agentd JSONL soketine tek komut gönder, yanıtı döndür."""
    request_id = f"request-{uuid4().hex[:16]}"
    message = {"kind": "command", "request_id": request_id, "command": command}
    for key, value in (payload or {}).items():
        message[key] = value
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
    with socket.create_connection((AGENTD_HOST, AGENTD_PORT), timeout=5.0) as sock:
        sock.settimeout(timeout)
        sock.sendall(line.encode("utf-8"))
        reader = sock.makefile("r", encoding="utf-8")
        while True:
            raw = reader.readline()
            if not raw:
                raise ConnectionError("agentd bağlantıyı kapattı")
            try:
                reply = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if reply.get("kind") != "event" or reply.get("request_id") == request_id:
                return reply


def harvest_snapshot() -> dict:
    """Tek gerçek kaynak: /home/mani/harvest (status.json + teslim kovaları)."""
    if _hstatus is None:
        return {"ok": False, "error": "harvest status modülü yok"}
    state = {}
    if _hstatus.STATUS.exists():
        try:
            state = json.loads(_hstatus.STATUS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}
    proxies, counts, candidates = _hstatus._read_proxies()
    return {
        "ok": True,
        "phase": state.get("phase", "bilinmiyor"),
        "target": state.get("target", "-"),
        "asn": state.get("asn", "-"),
        "tier": state.get("tier", "-"),
        "scanned_ips": int(state.get("scanned_ips", 0) or 0),
        "open_ports": int(state.get("open_ports", 0) or 0),
        "total_live": len(proxies),
        **counts,
        "candidates": candidates,
        "proxies": proxies,
    }


def systemctl(action: str, unit: str) -> dict:
    proc = subprocess.run(
        ["sudo", "-n", "systemctl", action, unit],
        capture_output=True, text=True, timeout=30,
    )
    active = subprocess.run(
        ["systemctl", "is-active", unit],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    return {
        "ok": proc.returncode == 0,
        "action": action,
        "unit": unit,
        "state": active,
        "stderr": proc.stderr.strip()[:500],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "PaidProxyAPI/1.0"

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        try:
            parsed = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def log_message(self, fmt, *args):  # erişim logu journal'ı doldurmasın
        pass

    def do_GET(self) -> None:  # noqa: N802
        path, _, query = self.path.partition("?")
        params: dict[str, str] = {}
        for part in query.split("&"):
            if "=" in part:
                key, _, value = part.partition("=")
                params[key] = value
        try:
            if path == "/api/health":
                agentd_ok = True
                try:
                    agentd_call("status", timeout=8.0)
                except Exception:
                    agentd_ok = False
                return self._send(200, {
                    "ok": agentd_ok,
                    "agentd": agentd_ok,
                    "harvest": HARVEST_STATUS.exists(),
                })
            if path == "/api/status":
                return self._send(200, agentd_call("status"))
            if path == "/api/harvest":
                return self._send(200, harvest_snapshot())
            if path == "/api/events":
                return self._send(200, agentd_call("replay", {
                    "agent_id": params.get("agent_id", ""),
                    "after_seq": int(params.get("after_seq", 0) or 0),
                    "limit": int(params.get("limit", 100) or 100),
                }))
            if path in ("/", "/api"):
                return self._send(200, {
                    "service": "paidproxy-api",
                    "endpoints": [
                        "GET /api/health",
                        "GET /api/status",
                        "GET /api/harvest",
                        "GET /api/events?agent_id=&after_seq=&limit=",
                        "POST /api/command",
                        "POST /api/scan/start",
                        "POST /api/scan/stop",
                        "POST /api/scan/restart",
                    ],
                })
            return self._send(404, {"ok": False, "error": f"bilinmeyen yol: {path}"})
        except Exception as exc:
            return self._send(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.partition("?")[0]
        body = self._read_json()
        try:
            if path == "/api/command":
                command = str(body.get("command", ""))
                if command not in COMMANDS:
                    return self._send(400, {"ok": False, "error": f"izinli komut değil: {command}"})
                payload = body.get("payload") or {}
                if not isinstance(payload, dict):
                    payload = {}
                return self._send(200, agentd_call(command, payload))
            if path == "/api/scan/start":
                return self._send(200, systemctl("start", "harvest.service"))
            if path == "/api/scan/stop":
                subprocess.run(["sudo", "-n", "pkill", "-9", "masscan"],
                               capture_output=True, timeout=15)
                return self._send(200, systemctl("stop", "harvest.service"))
            if path == "/api/scan/restart":
                return self._send(200, systemctl("restart", "harvest.service"))
            return self._send(404, {"ok": False, "error": f"bilinmeyen yol: {path}"})
        except Exception as exc:
            return self._send(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    parser = argparse.ArgumentParser(description="PaidProxy API Gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"paidproxy-api {args.host}:{args.port} — agentd {AGENTD_HOST}:{AGENTD_PORT}",
          file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
