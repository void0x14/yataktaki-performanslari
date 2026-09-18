#!/usr/bin/env python3
"""Kokpit köprüsü — tüm doğrulanmış veri TEK akışta, otonom.

Kaynaklar (ikisi de canlı, biri eski biri yeni üretim):
  /home/mani/paidproxy-otomasyon/var/teslim/  (geçmiş doğrulanmış havuz)
  /home/mani/harvest/var/teslim/              (aktif fabrika çıktısı)

Veri otonom akar: harvest.service sürekli üretir, bu betik kokpit her
sorgusunda iki depoyu birleştirip kokpitin beklediği şemayı basar.
JSONL yok. Manuel güncelleme yok. Betik yok — bu, köprünün veri
sağlayıcısıdır.

Çıktı şeması (cockpit/app/src/main.ts):
  open_ports, total_live, v6_count, v4_count, rotate_count, socks_count,
  connect_count, scan_progress, scan_log, proxies[{endpoint,protocol,
  version,type,rotation,egress}]
"""
import json
import sys
from pathlib import Path

STATUS = Path("/home/mani/harvest/var/harvest/status.json")
DEPOS = (
    Path("/home/mani/paidproxy-otomasyon/var/teslim"),  # geçmiş havuz
    Path("/home/mani/harvest/var/teslim"),              # aktif fabrika
)

# Kova dosyası → kokpit alanları
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

# Dev aday envanteri (doğrulanmış değil — sayı olarak raporlanır, listelenmez)
CANDIDATES = (
    Path("/home/mani/paidproxy-otomasyon/var/teslim/proxy_100k_batch1.txt"),
    Path("/home/mani/paidproxy-otomasyon/var/teslim/proxy_100k_batch2.txt"),
    Path("/home/mani/paidproxy-otomasyon/var/teslim/proxy_100k_batch3.txt"),
    Path("/home/mani/paidproxy-otomasyon/var/teslim/genlenmis_tum_proxyler_3M.txt"),
)


def _read_proxies() -> tuple[list, dict, int]:
    """İki depodan tüm doğrulanmış proxy'ler + sayaçlar + aday envanter sayısı."""
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
    candidates = 0
    for path in CANDIDATES:
        try:
            with path.open("rb") as fh:
                candidates += sum(1 for _ in fh)
        except OSError:
            continue
    return proxies, counts, candidates


def main() -> None:
    state = {}
    if STATUS.exists():
        try:
            state = json.loads(STATUS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}

    proxies, counts, candidates = _read_proxies()
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
        "scan_progress": (f"{phase} · hedef {target} · {asn} [{tier}] · "
                          f"{scanned:,} IP tarandı · {rate} pps"),
        "scan_log": (f"{phase}: {target} ({asn}, {tier}) — taranan {scanned:,} IP, "
                     f"açık {open_ports:,}, doğrulanmış {len(proxies)} "
                     f"(aday envanteri {candidates:,})"),
        "proxies": proxies,
        "phase": phase,
        "target": target,
        "asn": asn,
        "tier": tier,
        "scanned_ips": scanned,
        "candidates": candidates,
    }
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
