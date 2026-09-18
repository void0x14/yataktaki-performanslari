#!/usr/bin/env python3
"""Kokpit köprüsü — TEK canlı kaynak: /home/mani/harvest.

tauri_bridge.py `get_harvest_data` bu betiği VDS'te çalıştırır.
Veri otonom akar: harvest.service sürekli var/harvest/status.json ve
var/teslim/*.txt dosyalarını günceller; bu betik onları kokpitin
beklediği şemaya çevirir.

Çıktı şeması (cockpit/app/src/main.ts):
  open_ports, total_live, v6_count, v4_count, rotate_count, socks_count,
  connect_count, scan_progress, scan_log, proxies[{endpoint,protocol,
  version,type,rotation,egress}]
"""
import json
import sys
import time
from pathlib import Path

WORKDIR = Path("/home/mani/harvest")
STATUS = WORKDIR / "var/harvest/status.json"
LIVE_JSONL = WORKDIR / "var/harvest/live.jsonl"
TESLIM = WORKDIR / "var/teslim"

# Kova dosyası → kokpit alanları
BUCKET_META = {
    "v6_forward":    {"protocol": "HTTP-FWD", "version": "v6", "type": "forward", "rotation": "statik"},
    "v4_forward":    {"protocol": "HTTP-FWD", "version": "v4", "type": "forward", "rotation": "statik"},
    "rotate_proxies": {"protocol": "HTTP-FWD", "version": "v4", "type": "forward", "rotation": "rotate"},
    "http_fwd":      {"protocol": "HTTP-FWD", "version": "v4", "type": "forward", "rotation": "statik"},
    "http_connect":  {"protocol": "HTTP-CON", "version": "v4", "type": "connect", "rotation": "statik"},
    "socks5":        {"protocol": "SOCKS5", "version": "v4", "type": "socks5", "rotation": "statik"},
    "socks4":        {"protocol": "SOCKS4", "version": "v4", "type": "socks4", "rotation": "statik"},
    "socks4a":       {"protocol": "SOCKS4a", "version": "v4", "type": "socks4a", "rotation": "statik"},
    "socks":         {"protocol": "SOCKS5", "version": "v4", "type": "socks5", "rotation": "statik"},
}


def _egress_map() -> dict:
    """live.jsonl → {ip:port: egress_ip} — pipeline'ın yazdığı canlı kanıtlar."""
    out: dict[str, str] = {}
    if not LIVE_JSONL.exists():
        return out
    try:
        lines = LIVE_JSONL.read_text(encoding="utf-8").splitlines()[-20000:]
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        ip, port = rec.get("ip"), rec.get("port")
        if ip and port:
            out[f"{ip}:{port}"] = str(rec.get("egress") or "")
    return out


def _read_proxies() -> tuple[list, dict]:
    """Teslim kovalarından proxy listesi + sayaçlar."""
    egress = _egress_map()
    proxies: list = []
    counts = {"v6_count": 0, "v4_count": 0, "rotate_count": 0,
              "socks_count": 0, "connect_count": 0}
    if not TESLIM.is_dir():
        return proxies, counts
    for f in sorted(TESLIM.glob("*.txt")):
        meta = BUCKET_META.get(f.stem)
        if not meta:
            continue
        try:
            lines = [ln.strip() for ln in f.read_text().splitlines() if ln.strip()]
        except OSError:
            continue
        n = len(lines)
        if not n:
            continue
        pool = f.stem
        if pool == "v6_forward":
            counts["v6_count"] += n
        elif pool in ("v4_forward", "rotate_proxies", "http_fwd"):
            counts["v4_count"] += n
        elif pool in ("socks5", "socks4", "socks4a", "socks"):
            counts["socks_count"] += n
        elif pool == "http_connect":
            counts["connect_count"] += n
        if pool == "rotate_proxies":
            counts["rotate_count"] += n
        for endpoint in lines:
            proxies.append({
                "endpoint": endpoint,
                "protocol": meta["protocol"],
                "version": meta["version"],
                "type": meta["type"],
                "rotation": meta["rotation"] if pool != "rotate_proxies" else "rotate",
                "egress": egress.get(endpoint, ""),
            })
    return proxies, counts


def main() -> None:
    state = {}
    if STATUS.exists():
        try:
            state = json.loads(STATUS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}

    proxies, counts = _read_proxies()
    phase = state.get("phase", "bilinmiyor")
    target = state.get("target", "-")
    asn = state.get("asn", "-")
    tier = state.get("tier", "-")
    scanned = int(state.get("scanned_ips", 0) or 0)
    open_ports = int(state.get("open_ports", 0) or 0)
    rate = int(state.get("rate_pps", 0) or 0)

    out = {
        "ok": True,
        "open_ports": open_ports,
        "total_live": len(proxies),
        **counts,
        "scan_progress": f"{phase} · hedef {target} · {asn} [{tier}] · {scanned:,} IP tarandı · {rate} pps",
        "scan_log": f"{phase}: {target} ({asn}, {tier}) — taranan {scanned:,} IP, açık {open_ports:,}, canlı {len(proxies)}",
        "proxies": proxies,
        "phase": phase,
        "target": target,
        "asn": asn,
        "tier": tier,
        "scanned_ips": scanned,
        "updated": int(time.time()),
    }
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
