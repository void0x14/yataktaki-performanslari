"""Harvest orkestratörü — 7/24 otonom hasat döngüsü (VDS tarafı, stdlib-only).

Döngü — KURAL: masscan SADECE çapa portlarını tarar (10K/30K/60K), aralık yasak:
  1. TargetEngine.pick_targets()  — ülke/ASN/prefix, koku skoru, ölü zemin yasağı
  2. Pilot ısırık — çapa portlarıyla örneklem dilimi
  3. Yayılma     — yine SADECE çapa portları (masscanda aralık YOK)
  4. GENLE       — canlı IP × 10000-65000 adayları script tarafında üretilir
  5. CHECK       — xRisky tarzı ALL-TYPE proxy checker doğrular
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
from checker import run_batch as checker_batch

# KURAL: masscan SADECE çapa portlarını tarar — 10K / 30K / 60K.
# Aralık taraması YASAK. Genleme (10000-65000 aday üretimi) script tarafında,
# doğrulama xRisky tarzı ALL-TYPE proxy checker ile yapılır.
ANCHOR_PORTS = [10000, 30000, 60000]
PILOT_SAMPLE = 256                # pilot ısırık örneklem boyutu
EXPAND_CHUNK = 65536              # yayılma masscan parça boyutu (IP sayısı)
GEN_PORT_LOW = 10000              # genleme aralığı: 55.000 aday/IP
GEN_PORT_HIGH = 65000
GEN_MAX_IPS = 24                  # tur başına genlenecek canlı IP sayısı
CHECK_BATCH = 50_000              # tur başına checkera verilecek aday


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


def masscan(targets: list[str], ports: "list[int] | str", rate: int,
            wait: int = 3, binary: str = "masscan") -> list[tuple[str, int]]:
    """L4 SYN taraması — dönüş: [(ip, port)]. ports: liste ya da aralık dizgesi ("10000-65535")."""
    if not targets or not ports:
        return []
    port_spec = ports if isinstance(ports, str) else ",".join(str(p) for p in ports)
    cmd = [binary, *targets, "-p", port_spec,
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


def _merge_farms(workdir: Path, pairs: list[tuple[str, int]],
                 verdicts: list | None = None) -> None:
    """Çiftlik raporu (kalıcı): ip başına açık port sayısı + doğrulanmış + örnek portlar.

    Kokpit 'tek IP'de çoklu port' görünümünü bu dosyadan okur:
    var/harvest/ciftlikler.json
    """
    path = workdir / "var/harvest/ciftlikler.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = {}
    if not isinstance(report, dict):
        report = {}
    now = int(time.time())
    counts: dict[str, int] = {}
    samples: dict[str, list[int]] = {}
    for ip, port in pairs:
        counts[ip] = counts.get(ip, 0) + 1
        bucket = samples.setdefault(ip, [])
        if len(bucket) < 12 and port not in bucket:
            bucket.append(port)
    for ip, n in counts.items():
        rec = report.get(ip)
        if not isinstance(rec, dict):
            rec = {"open": 0, "verified": 0, "sample": [], "ts": 0}
        rec["open"] = max(int(rec.get("open", 0) or 0), n)
        existing = [int(p) for p in (rec.get("sample") or [])]
        for port in samples.get(ip, []):
            if port not in existing and len(existing) < 12:
                existing.append(port)
        rec["sample"] = existing
        rec["ts"] = now
        report[ip] = rec
    if verdicts:
        verified: dict[str, int] = {}
        for v in verdicts:
            if isinstance(v, dict):
                ip = str(v.get("endpoint", "")).rpartition(":")[0]
                if ip:
                    verified[ip] = verified.get(ip, 0) + 1
            elif getattr(v, "alive", False):
                ip = str(getattr(v, "ip", ""))
                if ip:
                    verified[ip] = verified.get(ip, 0) + 1
        for ip, n in verified.items():
            rec = report.get(ip)
            if not isinstance(rec, dict):
                rec = {"open": 0, "verified": 0, "sample": [], "ts": now}
            rec["verified"] = max(int(rec.get("verified", 0) or 0), n)
            rec["ts"] = now
            report[ip] = rec
    # Rapor şişmesin: anlamlı kayıtlar kalır
    cutoff = now - 86400 * 3
    report = {
        ip: rec for ip, rec in report.items()
        if isinstance(rec, dict) and (
            int(rec.get("open", 0) or 0) >= 2
            or int(rec.get("verified", 0) or 0) > 0
            or int(rec.get("ts", 0) or 0) >= cutoff
        )
    }
    try:
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def genle(workdir: Path, ips: list[str]) -> int:
    """GENLEME: canlı IP × 10000-65000 adaylarını havuza yaz (masscan YOK).

    Kural birebir: masscan sadece çapa portlarını tarar; 10K-65K genlemesi
    script tarafında aday üretimidir, doğrulaması checker'a aittir.
    """
    path = workdir / "var/harvest/gen_queue.txt"
    count = 0
    try:
        with path.open("a", encoding="utf-8") as fh:
            for ip in ips:
                for port in range(GEN_PORT_LOW, GEN_PORT_HIGH):
                    fh.write(f"{ip}:{port}\n")
                    count += 1
    except OSError:
        return 0
    return count

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
            for cidr in t["prefixes"]:
              try:
                ports_key = ",".join(map(str, ANCHOR_PORTS))
                if ledger.is_scanned(cidr, ports_key):
                    continue

                # --- Aşama 2: Pilot ısırık (SADECE çapa portları: 10K/30K/60K) ---
                sample = pilot_sample(cidr)
                status.update(phase="pilot", target=cidr,
                              asn=f"AS{t['asn']}", tier=t["tier"], rate_pps=rate)
                hits = masscan(sample, ANCHOR_PORTS, rate)
                scanned_ips += len(sample)

                if not hits:
                    ledger.record(cidr, ports_key, 0)
                    status.update(phase="skip-dead", target=cidr,
                                  scanned_ips=scanned_ips)
                    continue

                # --- Aşama 3: Yayılma (yine SADECE çapa portları — aralık YOK) ---
                status.update(phase="expand", target=cidr, scanned_ips=scanned_ips)
                chunks = expand_ranges(cidr)
                hits = masscan(chunks, ANCHOR_PORTS, rate)
                scanned_ips += sum(
                    ipaddress.ip_network(c, strict=False).num_addresses for c in chunks
                )
                open_ports += len(hits)
                ledger.record(cidr, ports_key, len(hits))

                if not hits:
                    continue

                # --- Aşama 4: GENLE — canlı IP × 10000-65000 adayları (script üretimi) ---
                farm_ips = sorted({ip for ip, _ in hits})
                uretilen = genle(workdir, farm_ips[:GEN_MAX_IPS])
                status.update(phase="genle", target=cidr, scanned_ips=scanned_ips,
                              open_ports=open_ports, asn=f"uretildi:{uretilen}")

                # --- Aşama 5: CHECK — xRisky tarzı ALL-TYPE proxy checker ---
                status.update(phase="check", target=cidr, scanned_ips=scanned_ips,
                              open_ports=open_ports)
                stats = checker_batch(workdir, limit=CHECK_BATCH)
                _merge_farms(workdir, hits, stats.get("verified") or [])
                engine.record_hit(t["asn"], int(stats.get("alive", 0)))

                # --- Aşama 6: Teslim raporu (kovaları checker yazar) ---
                live_now = {}
                if teslim.is_dir():
                    for f in sorted(teslim.glob("*.txt")):
                        try:
                            n = sum(1 for ln in f.read_text().splitlines() if ln.strip())
                        except OSError:
                            continue
                        if n:
                            live_now[f.stem] = n
                            totals.setdefault(f.name, set()).update(range(n))
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
