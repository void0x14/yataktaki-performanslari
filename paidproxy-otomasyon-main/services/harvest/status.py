#!/usr/bin/env python3
"""Kokpit köprüsü — var/harvest/status.json + var/teslim sayaçlarını JSON döner.

tauri_bridge.py `get_harvest_data` bu betiği VDS'te çalıştırır;
tek gerçek kaynak harvest pipeline'ın yazdığı status.json'dur.
"""
import json
import sys
from pathlib import Path

WORKDIR = Path("/home/mani/harvest")
STATUS = WORKDIR / "var/harvest/status.json"
TESLIM = WORKDIR / "var/teslim"


def main() -> None:
    state = {}
    if STATUS.exists():
        try:
            state = json.loads(STATUS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}

    buckets = {}
    total_live = 0
    if TESLIM.is_dir():
        for f in sorted(TESLIM.glob("*.txt")):
            try:
                n = sum(1 for line in f.read_text().splitlines() if line.strip())
            except OSError:
                n = 0
            if n:
                buckets[f.stem] = n
                total_live += n

    out = {
        "ok": True,
        "phase": state.get("phase", "unknown"),
        "target": state.get("target", "-"),
        "asn": state.get("asn", "-"),
        "tier": state.get("tier", "-"),
        "scanned_ips": state.get("scanned_ips", 0),
        "open_ports": state.get("open_ports", 0),
        "rate_pps": state.get("rate_pps", 0),
        "uptime_s": int(__import__("time").time() - state.get("started", 0)) if state.get("started") else 0,
        "total_live": total_live,
        "buckets": buckets,
    }
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
