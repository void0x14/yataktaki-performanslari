"""Harvest orkestratörü — 7/24 otonom hasat döngüsü (VDS tarafı, stdlib-only).

Döngü (specs/otonom-avci-ve-saha-verisi-mimarisi.md 10 Yapı Taşı):
  1. TargetEngine.pick_targets()  — ülke/ASN/prefix, koku skoru, ölü zemin yasağı
  2. Pilot ısırık — prefix'in örneklem dilimine kokuya uygun TEK ilk diş
  3. Genleme     — canlı damar → range tamamı + çapa port ailesi
  4. Kovan       — çapa veren IP'lere 10000-40000 genleme
  5. Sınıflandır — 5-protokol + egress (v6/rotate/v4) kovalama
  6. Teslim      — var/teslim/<kova>.txt (saf ip:port), status.json
  7. Ledger      — mükerrer tarama yasağı, kardeş damar kaydı

Çalıştırma (VDS):
  python3 pipeline.py --countries TR DE RU CN BR US --rate 4000
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import random
import sqlite3
import subprocess
import time
from pathlib import Path

from ripe import TargetEngine
from classify import classify_batch, bucket_files

# Kokuya göre ilk diş — SADECE 5-6 haneli portlar (10000-65535).
# 4 haneli port (3128, 8080, 1080...) lamer portudur: reputation'ı düşük,
# ömrü saatlik, her script kiddie oraya bakar. Gerçek kuyu 5-6 hanededir.
TIER_PORTS = {
    "P1": [10808, 10809, 10000, 12000, 20000, 31280],  # hosting/VPS — 10808 v2ray damarı kanıtlı
    "P2": [10808, 30000, 40000, 45000],                # kurumsal/statik
    "P3": [10808, 50000, 60000, 61000, 62000],         # residential/CPE
    "default": [10808, 10809, 10000, 12000, 20000, 30000, 40000, 50000, 60000],
}
FARM_EXPANSION = (10000, 40000)   # çapa veren IP'nin genlenecek port aralığı
PILOT_SAMPLE = 256                # pilot ısırık örneklem boyutu
EXPAND_CHUNK = 65536              # genleme masscan parça boyutu (IP sayısı)


class Ledger:
    """Mükerrer tarama yasağı + isabet defteri (Yapı Taşı 10)."""

    def __init__(self, path: str | Path = "var/harvest/ledger.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS scanned (target TEXT, ports TEXT, ts REAL, alive INTEGER)"
        )
        self.db.commit()

    def is_scanned(self, target: str, ports_key: str, max_age: float = 86400 * 3) -> bool:
        row = self.db.execute(
            "SELECT ts FROM scanned WHERE target=? AND ports=? ORDER BY ts DESC LIMIT 1",
            (target, ports_key),
        ).fetchone()
        return bool(row and (time.time() - row[0]) < max_age)

    def record(self, target: str, ports_key: str, alive: int) -> None:
        self.db.execute(
            "INSERT INTO scanned (target, ports, ts, alive) VALUES (?,?,?,?)",
            (target, ports_key, time.time(), alive),
        )
        self.db.commit()


class StatusWriter:
    """Kokpitin okuduğu tek gerçek — var/harvest/status.json."""

    def __init__(self, path: str | Path = "var/harvest/status.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = {
            "phase": "boot", "target": "-", "asn": "-", "tier": "-",
            "scanned_ips": 0, "open_ports": 0, "live": {},
            "rate_pps": 0, "started": time.time(), "updated": time.time(),
        }

    def update(self, **kw) -> None:
        self.state.update(kw)
        self.state["updated"] = time.time()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)


def masscan(targets: list[str], ports: list[int], rate: int,
            wait: int = 3, binary: str = "masscan") -> list[tuple[str, int]]:
    """L4 SYN taraması — dönüş: [(ip, port)]."""
    if not targets or not ports:
        return []
    cmd = [binary, *targets, "-p", ",".join(str(p) for p in ports),
           "--rate", str(rate), "--wait", str(wait), "-oL", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    except subprocess.TimeoutExpired:
        return []
    out = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "open":
            try:
                out.append((parts[3], int(parts[2])))
            except (ValueError, IndexError):
                continue
    return out


def pilot_sample(cidr: str, size: int = PILOT_SAMPLE) -> list[str]:
    """Devasa bloğa körü körüne girilmez — örneklem dilimi (Yapı Taşı 4)."""
    net = ipaddress.ip_network(cidr, strict=False)
    total = net.num_addresses
    if total <= size:
        return [cidr]
    # Host listesini ASLA materyalize etme — /14'te 262k, /8'de 16M IP patlatır.
    # Rastgele offset örnekleme: O(size) bellek, prefix boyutundan bağımsız.
    base = int(net.network_address)
    inner = max(1, total - 2)
    random.seed(base)
    picks = random.sample(range(1, inner + 1), min(size, inner))
    return [str(ipaddress.ip_address(base + i)) for i in picks]


def expand_ranges(cidr: str, chunk: int = EXPAND_CHUNK) -> list[str]:
    """Prefix'i masscan parçalarına böl — /24 hapsi yok, parça dinamik."""
    net = ipaddress.ip_network(cidr, strict=False)
    if net.num_addresses <= chunk:
        return [str(net)]
    return [str(sub) for sub in net.subnets(new_prefix=min(32, net.prefixlen + 8))]


def run_pipeline(countries: list[str], rate: int, workdir: Path,
                 max_asn: int = 5, once: bool = False) -> None:
    engine = TargetEngine(cache_db=workdir / "var/harvest/ripe_cache.db")
    ledger = Ledger(workdir / "var/harvest/ledger.db")
    status = StatusWriter(workdir / "var/harvest/status.json")
    teslim = workdir / "var/teslim"
    teslim.mkdir(parents=True, exist_ok=True)

    totals: dict[str, set] = {}
    scanned_ips = 0
    open_ports = 0
    cycle = 0
    while True:
        try:
            targets = engine.pick_targets(countries, max_asn_per_country=max_asn,
                                          asn_offset=cycle)
        except Exception as exc:
            status.update(phase="retry", target=f"pick-hata:{type(exc).__name__}")
            time.sleep(120)
            continue
        if not targets:
            status.update(phase="idle", target="hedef-yok")
            time.sleep(300)
            continue

        for t in targets:
            tier_ports = TIER_PORTS.get(t["tier"], TIER_PORTS["default"])
            for cidr in t["prefixes"]:
              try:
                ports_key = ",".join(map(str, tier_ports))
                if ledger.is_scanned(cidr, ports_key):
                    continue

                # --- Aşama 2: Pilot ısırık ---
                sample = pilot_sample(cidr)
                status.update(phase="pilot", target=cidr,
                              asn=f"AS{t['asn']}", tier=t["tier"], rate_pps=rate)
                hits = masscan(sample, tier_ports[:1], rate)  # tek ilk diş
                scanned_ips += len(sample)

                if not hits:
                    ledger.record(cidr, ports_key, 0)
                    status.update(phase="skip-dead", target=cidr,
                                  scanned_ips=scanned_ips)
                    continue

                # --- Aşama 3: Damar canlı → genleme ---
                status.update(phase="expand", target=cidr, scanned_ips=scanned_ips)
                chunks = expand_ranges(cidr)
                hits = masscan(chunks, tier_ports, rate)
                scanned_ips += sum(
                    ipaddress.ip_network(c, strict=False).num_addresses for c in chunks
                )
                open_ports += len(hits)
                ledger.record(cidr, ports_key, len(hits))

                if not hits:
                    continue

                # --- Aşama 4: Kovan genleme (çapa veren IP'ler) ---
                farm_ips = sorted({ip for ip, _ in hits})
                farm_targets = []
                lo, hi = FARM_EXPANSION
                farm_ports = list(range(lo, hi + 1, 25))  # seyrek kovan dişi
                farm_hits = masscan(farm_ips, farm_ports, rate)
                all_hits = sorted(set(hits) | set(farm_hits))
                open_ports += len(farm_hits)

                # --- Aşama 5: Sınıflandırma ---
                status.update(phase="classify", target=cidr,
                              open_ports=open_ports, scanned_ips=scanned_ips)
                verdicts = asyncio.run(classify_batch(all_hits, concurrency=500))
                buckets = bucket_files(verdicts)

                # --- Aşama 6: Teslim (saf ip:port, kova adında tür) ---
                live_now = {}
                for fname, lines in buckets.items():
                    kova = teslim / fname
                    existing = set()
                    if kova.exists():
                        existing = set(kova.read_text().split())
                    new = existing | set(lines)
                    kova.write_text("\n".join(sorted(new)) + "\n")
                    live_now[fname.replace(".txt", "")] = len(new)
                    totals.setdefault(fname, set()).update(lines)

                alive_count = sum(1 for v in verdicts if v.alive)
                engine.record_hit(t["asn"], alive_count)
                status.update(phase="deliver", target=cidr,
                              scanned_ips=scanned_ips, open_ports=open_ports,
                              live=live_now)
              except Exception as exc:
                status.update(phase="target-error", target=cidr,
                              asn=f"{type(exc).__name__}")
                continue

        if once:
            break
        status.update(phase="cycle-done", scanned_ips=scanned_ips,
                      open_ports=open_ports,
                      live={k.replace(".txt", ""): len(v) for k, v in totals.items()})
        cycle += 1
        time.sleep(60)


def main() -> None:
    ap = argparse.ArgumentParser(description="Harvest otonom hasat boru hattı")
    ap.add_argument("--countries", nargs="+", default=["TR", "DE", "RU", "BR", "CN"])
    ap.add_argument("--rate", type=int, default=4000, help="masscan pps (güvenli: 4000)")
    ap.add_argument("--workdir", type=Path, default=Path("."))
    ap.add_argument("--max-asn", type=int, default=5)
    ap.add_argument("--once", action="store_true", help="tek döngü çalıştır ve çık")
    args = ap.parse_args()
    run_pipeline(args.countries, args.rate, args.workdir, args.max_asn, args.once)


if __name__ == "__main__":
    main()
