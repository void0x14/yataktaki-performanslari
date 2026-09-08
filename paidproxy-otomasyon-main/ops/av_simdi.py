#!/usr/bin/env python3
"""Koku al, ısır, kan yoksa bırak. CIDR sormaz. Teslime yalnız çıkışlı uç yazar."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/void0x14/Belgeler/paidproxy-otomasyon-main")
os.chdir(ROOT)
import sys
sys.path[:0] = ["src", "cockpit"]

from proxy_pipeline.validators.protocols import (  # noqa: E402
    HTTPConnectValidator,
    SOCKS4Validator,
    SOCKS5Validator,
    ValidationResult,
)

YASAK = {13335, 15169, 16509, 8075, 32934, 13335}
SSH = ["ssh", "-i", str(Path.home() / ".ssh" / "paidproxy_vds"),
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "mani@20.207.198.170"]
IZ = ROOT / "var" / "yuruyus" / "yuruyus.jsonl"
TESLIM = ROOT / "var" / "teslim"
IZ.parent.mkdir(parents=True, exist_ok=True)
TESLIM.mkdir(parents=True, exist_ok=True)

KELIME_PORT = [
    ("colo hosting", 8080),
    ("cache proxy", 3128),
    ("broadband static", 1080),
    ("reseller hosting", 3128),
    ("vps hosting", 8080),
]


def ripe_json(path: str, resource: str) -> dict:
    q = urllib.parse.urlencode({"resource": resource})
    url = f"https://stat.ripe.net/data/{path}/data.json?{q}"
    with urllib.request.urlopen(url, timeout=12) as r:
        return json.loads(r.read().decode())


def kokulu_asler() -> list[tuple[int, int, str]]:
    aday: list[tuple[int, int, str]] = []
    for kelime, port in KELIME_PORT:
        try:
            data = ripe_json("searchcomplete", kelime)
        except Exception:
            continue
        for cat in (data.get("data") or {}).get("categories") or []:
            if cat.get("category") != "ASNs":
                continue
            for rec in cat.get("suggestions") or []:
                m = re.search(r"AS(\d+)", str(rec.get("value") or ""), re.I)
                if not m:
                    continue
                asn = int(m.group(1))
                if asn in YASAK:
                    continue
                desc = str(rec.get("description") or rec.get("label") or "")
                aday.append((asn, port, desc))
    seen = set()
    uniq = []
    for a in aday:
        if a[0] in seen:
            continue
        seen.add(a[0])
        uniq.append(a)
    return uniq


def prefix(asn: int) -> str | None:
    try:
        data = ripe_json("announced-prefixes", f"AS{asn}")
    except Exception:
        return None
    for p in (data.get("data") or {}).get("prefixes") or []:
        pref = p.get("prefix") or ""
        if ":" in pref:
            continue
        try:
            net = ipaddress.ip_network(pref, strict=False)
        except ValueError:
            continue
        if net.prefixlen > 24:
            continue
        hedef = net if net.prefixlen == 24 else next(net.subnets(new_prefix=24))
        return str(hedef)
    return None


def masscan(cidr: str, port: int) -> list[str]:
    cmd = (f"sudo masscan {cidr} -p{port} --rate 500 --wait 2 -oL - "
           f"2>/dev/null | grep '^open ' || true")
    p = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=40)
    ips = []
    for line in (p.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "open":
            ips.append(parts[3])
    return ips


def dogrula(ip: str, port: int) -> dict | None:
    for v in (HTTPConnectValidator(), SOCKS5Validator(), SOCKS4Validator()):
        son = v.validate(ip, port, timeout=3.5, target=("stat.ripe.net", 443))
        if son.result == ValidationResult.VALIDATED:
            return {"ip": ip, "port": port, "protokol": son.protocol,
                    "cikis": son.exit_ip, "ms": son.latency_ms}
        if son.result == ValidationResult.AUTH_REQUIRED:
            return None
    return None


def yaz(adim: str, **kw):
    kw["adim"] = adim
    kw["zaman"] = datetime.now(timezone.utc).isoformat()
    with IZ.open("a") as f:
        f.write(json.dumps(kw, ensure_ascii=False) + "\n")


def teslim_yaz(kayitlar: list[dict]):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    p = TESLIM / f"teslim-{stamp}.jsonl"
    with p.open("a") as f:
        for r in kayitlar:
            r = dict(r)
            r["zaman"] = datetime.now(timezone.utc).isoformat()
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def main():
    asler = kokulu_asler()
    yaz("av-basla", as_sayisi=len(asler))
    kan = []
    for asn, port, desc in asler[:18]:
        pref = prefix(asn)
        if not pref:
            yaz("birak", asn=asn, neden="prefix yok")
            continue
        yaz("isirik", asn=asn, cidr=pref, port=port, koku=desc)
        try:
            ips = masscan(pref, port)
        except Exception as e:
            yaz("birak", asn=asn, cidr=pref, neden=str(e))
            continue
        if not ips:
            yaz("olu", asn=asn, cidr=pref, port=port)
            continue
        yaz("canli", asn=asn, cidr=pref, port=port, ips=ips[:20], adet=len(ips))
        for ip in ips[:12]:
            rec = dogrula(ip, port)
            if not rec:
                continue
            rec.update({"asn": asn, "cidr": pref, "neden": desc, "koku": desc})
            kan.append(rec)
            yaz("kan", **rec)
        if kan:
            path = teslim_yaz(kan)
            yaz("teslim", path=str(path), adet=len(kan))
            return 0
        time.sleep(0.3)
    yaz("bitti", kan=len(kan))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
