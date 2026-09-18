#!/usr/bin/env python3
"""Kokpit köprüsü + API veri katmanı — TEK canlı kaynak: /home/mani/harvest.

tauri_bridge.py `get_harvest_data` ve paidproxy-api `/api/harvest` bu
modülü kullanır. Kurallar: JSONL yok, /tmp yok — her şey kalıcı.
Hız: aday sayımı mtime-kilitli önbellekte; çağrı < 1 sn.

Çıktı şeması (cockpit/app/src/main.ts):
  open_ports, total_live, v6_count, v4_count, rotate_count, socks_count,
  connect_count, scan_progress, scan_log, proxies[{endpoint,protocol,
  version,type,rotation,egress}], farms[{ip,open,verified,sample}]
"""
import json
import sys
from pathlib import Path

STATUS = Path("/home/mani/harvest/var/harvest/status.json")
FARMS = Path("/home/mani/harvest/var/harvest/ciftlikler.json")
CAND_CACHE = Path("/home/mani/harvest/var/harvest/candidates.cache.json")
DEPOS = (
    Path("/home/mani/paidproxy-otomasyon/var/teslim"),  # geçmiş havuz
    Path("/home/mani/harvest/var/teslim"),              # aktif fabrika
)

BUCKET_META = {
    "v6_forward":     {"protocol": "HTTP-FWD", "version": "v6", "type": "forward", "rotation": "statik"},
    "v4_forward":     {"protocol": "HTTP-FWD", "version": "v4", "type": "forward", "rotation": "statik"},
    "rotate_proxies": {"protocol": "HTTP-FWD", "version": "v4", "type": "forward", "rotation": "rotate"},
    "http_fwd":       {"protocol": "HTTP-FWD", "version": "v4", "type": "forward", "rotation": "statik"},
    "http_connect":   {"protocol": "HTTP-CON", "version": "v4", "type": "connect", "rotation": "statik"},
    "socks5":         {"protocol": "SOCKS5", "version": "v4", "type": "socks5", "rotation": "statik"},
    "socks4":         {"protocol": "SOCKS4", "version": "v4", "type": "socks4", "rotation": "statik"},
    "socks4a":        {"protocol": "SOCKS4a", "version": "v4", "type": "socks4a", "rotation": "statik"},
    "socks":          {"protocol": "SOCKS5", "version": "v4", "type": "socks5", "rotation": "statik"},
}

def _candidate_files() -> list[Path]:
    """Aday dosyaları DİNAMİK keşfedilir: depolardaki doğrulanmış kova OLMAYAN
    her .txt aday envanteridir. Sabit dosya adı yok."""
    out = []
    for depo in DEPOS:
        if not depo.is_dir():
            continue
        for f in sorted(depo.glob("*.txt")):
            if f.stem in BUCKET_META:
                continue  # doğrulanmış kova — aday değil
            out.append(f)
    return out


def _port_key(endpoint: str) -> tuple:
    host, _, port = endpoint.rpartition(":")
    try:
        return (host, int(port))
    except ValueError:
        return (endpoint, 0)


def _read_proxies() -> tuple[list, dict, int]:
    """İki depodan doğrulanmış proxy'ler (ip, port sıralı) + sayaçlar + aday sayısı."""
    proxies: list = []
    seen: set = set()
    counts = {"v6_count": 0, "v4_count": 0, "rotate_count": 0,
              "socks_count": 0, "connect_count": 0}
    for depo in DEPOS:
        if not depo.is_dir():
            continue
        for f in sorted(depo.glob("*.txt")):
            meta = BUCKET_META.get(f.stem)
            if not meta:
                continue
            try:
                lines = [ln.strip() for ln in f.read_text().splitlines() if ln.strip()]
            except OSError:
                continue
            pool = f.stem
            for endpoint in lines:
                if endpoint in seen:
                    continue
                seen.add(endpoint)
                if pool == "v6_forward":
                    counts["v6_count"] += 1
                elif pool in ("v4_forward", "rotate_proxies", "http_fwd"):
                    counts["v4_count"] += 1
                    if pool == "rotate_proxies":
                        counts["rotate_count"] += 1
                elif pool in ("socks5", "socks4", "socks4a", "socks"):
                    counts["socks_count"] += 1
                elif pool == "http_connect":
                    counts["connect_count"] += 1
                proxies.append({
                    "endpoint": endpoint,
                    "protocol": meta["protocol"],
                    "version": meta["version"],
                    "type": meta["type"],
                    "rotation": "rotate" if pool == "rotate_proxies" else meta["rotation"],
                    "egress": "",
                })
    proxies.sort(key=lambda p: _port_key(p["endpoint"]))
    return proxies, counts, _candidate_count()


def _candidate_count() -> int:
    """Aday envanteri — mtime/boyut anahtarlı önbellek. Her çağrıda 3.3M satır okunmaz."""
    files = _candidate_files()
    key_parts = []
    for path in files:
        try:
            st = path.stat()
        except OSError:
            continue
        key_parts.append(f"{path.name}:{st.st_size}:{int(st.st_mtime)}")
    key = "|".join(key_parts)
    try:
        cached = json.loads(CAND_CACHE.read_text(encoding="utf-8"))
        if cached.get("key") == key:
            return int(cached.get("count", 0))
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    count = 0
    for path in files:
        try:
            with path.open("rb") as fh:
                while True:
                    chunk = fh.read(4 << 20)
                    if not chunk:
                        break
                    count += chunk.count(b"\n")
        except OSError:
            continue
    try:
        CAND_CACHE.write_text(json.dumps({"key": key, "count": count}), encoding="utf-8")
    except OSError:
        pass
    return count


def _read_farms(limit: int = 60) -> list:
    """Çiftlik raporu — pipeline'ın yazdığı ciftlikler.json (anlık okuma)."""
    try:
        report = json.loads(FARMS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(report, dict):
        return []
    farms = []
    for ip, rec in report.items():
        if not isinstance(rec, dict):
            continue
        farms.append({
            "ip": ip,
            "open": int(rec.get("open", 0) or 0),
            "verified": int(rec.get("verified", 0) or 0),
            "sample": [int(p) for p in (rec.get("sample") or [])][:12],
        })
    farms.sort(key=lambda f: -f["open"])
    return farms[:limit]


def build_payload() -> dict:
    state = {}
    if STATUS.exists():
        try:
            state = json.loads(STATUS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}

    proxies, counts, candidates = _read_proxies()
    farms = _read_farms()
    phase = state.get("phase", "bilinmiyor")
    target = state.get("target", "-")
    asn = state.get("asn", "-")
    tier = state.get("tier", "-")
    scanned = int(state.get("scanned_ips", 0) or 0)
    open_ports = int(state.get("open_ports", 0) or 0)
    rate = int(state.get("rate_pps", 0) or 0)

    progress = f"{phase} · hedef {target} · {asn} [{tier}] · {scanned:,} IP tarandı · {rate} pps"
    if farms:
        lead = farms[0]
        progress += f" · lider çiftlik {lead['ip']} ({lead['open']:,} port)"

    return {
        "ok": True,
        "open_ports": open_ports,
        "total_live": len(proxies),
        **counts,
        "scan_progress": progress,
        "scan_log": (f"{phase}: {target} ({asn}, {tier}) — taranan {scanned:,} IP, "
                     f"açık {open_ports:,}, doğrulanmış {len(proxies)}, "
                     f"çiftlik {len(farms)}, aday envanteri {candidates:,}"),
        "proxies": proxies,
        "farms": farms,
        "phase": phase,
        "target": target,
        "asn": asn,
        "tier": tier,
        "scanned_ips": scanned,
        "candidates": candidates,
    }


def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
