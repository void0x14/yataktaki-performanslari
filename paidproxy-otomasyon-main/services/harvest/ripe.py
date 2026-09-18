"""RIPEstat hedef motoru — ülke/ASN/prefix keşfi, koku skoru, ölü zemin yasağı.

Kurallar (specs/otonom-avci-ve-saha-verisi-mimarisi.md Yapı Taşı 1-4):
  - Statik /24 hapsi YOK: prefix boyutu BGP anonsundan okunur (/12../24).
  - Ölü zemin: Cloudflare, Google, Microsoft, AWS, savunma/banka → asla taranmaz.
  - Öncelik: P1 unmanaged hosting > P2 kurumsal statik > P3 mobil/residential CGNAT.
  - Kardeş damar: son isabet ASN'i ve komşuları her zaman en önde.

Stdlib-only: urllib + json + sqlite3 kalıcı önbellek.
"""
from __future__ import annotations

import ipaddress
import json
import sqlite3
import time
from pathlib import Path
from urllib.request import Request, urlopen

RIPESTAT = "https://stat.ripe.net/data"

# Ölü zemin — kesinlikle taranmaz (Yapı Taşı 3)
DEAD_ASNS = {
    13335,   # Cloudflare
    15169,   # Google
    8075,    # Microsoft Azure
    16509,   # AWS
    14618,   # AWS
    32934,   # Facebook
    714,     # Apple
    2906,    # Netflix
    36459,   # GitHub
    20940,   # Akamai
    16625,   # Akamai
    396982,  # Google Cloud
    19551,   # Incapsula
    13414,   # Twitter/X
    63179,   # Cloudflare secondary
}

DEAD_HOLDER_KEYWORDS = (
    "cloudflare", "google", "microsoft", "azure", "amazon", "aws",
    "facebook", "apple", "netflix", "akamai", "github", "incapsula",
    "bank", "ministry", "government", "defence", "defense", "military",
)

# Koku tetikleyicileri (Yapı Taşı 1)
P1_KEYWORDS = (  # unmanaged hosting / VPS — hızlı kovan
    "hosting", "vps", "vds", "colo", "colocation", "server", "dedicated",
    "reseller", "data center", "datacenter", "cloud", "unmanaged",
)
P3_KEYWORDS = (  # mobil / residential — piyasa değeri en yüksek
    "mobile", "4g", "5g", "lte", "gsm", "cellular",
    "broadband", "pppoe", "dynamic", "pool", "residential",
    "dsl", "adsl", "vdsl", "fiber", "cable", "customer",
)
P2_KEYWORDS = (  # küçük kurumsal / statik — uzun ömür
    "isp", "telecom", "communications", "network", "internet",
    "enterprise", "business", "corporate",
)


class TargetEngine:
    """RIPEstat üzerinden hedef keşfi ve önceliklendirme."""

    def __init__(self, cache_db: str | Path = "var/harvest/ripe_cache.db") -> None:
        self.cache_path = Path(cache_db)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.cache_path))
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, payload TEXT, ts REAL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS hits (asn INTEGER PRIMARY KEY, last_hit REAL, yield_count INTEGER DEFAULT 0)"
        )
        self.db.commit()

    # ---------- HTTP + cache ----------

    def _get(self, endpoint: str, ttl: float = 86400.0) -> dict:
        key = endpoint
        row = self.db.execute("SELECT payload, ts FROM cache WHERE key=?", (key,)).fetchone()
        if row and (time.time() - row[1]) < ttl:
            return json.loads(row[0])
        url = f"{RIPESTAT}/{endpoint}"
        req = Request(url, headers={"Accept": "application/json", "User-Agent": "harvest/1.0"})
        with urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
        self.db.execute(
            "INSERT OR REPLACE INTO cache (key, payload, ts) VALUES (?,?,?)",
            (key, json.dumps(payload), time.time()),
        )
        self.db.commit()
        return payload

    # ---------- RIPEstat sorguları ----------

    def country_resources(self, country: str) -> dict:
        """Ülkenin tüm ASN + prefix envanteri (country-resource-list)."""
        data = self._get(f"country-resource-list/data.json?resource={country.upper()}", ttl=86400 * 7)
        res = data.get("data", {}).get("resources", {})
        return {
            "asn": [int(a) for a in res.get("asn", []) if str(a).isdigit()],
            "ipv4": list(res.get("ipv4", [])),
            "ipv6": list(res.get("ipv6", [])),
        }

    def as_overview(self, asn: int) -> dict:
        data = self._get(f"as-overview/data.json?resource=AS{asn}", ttl=86400)
        d = data.get("data", {})
        return {"holder": d.get("holder", "") or "", "announced": bool(d.get("announced"))}

    def announced_prefixes(self, asn: int) -> list[str]:
        data = self._get(f"announced-prefixes/data.json?resource=AS{asn}", ttl=86400)
        out = []
        for p in data.get("data", {}).get("prefixes", []) or []:
            pref = p.get("prefix") if isinstance(p, dict) else p
            if pref and ":" not in str(pref):
                out.append(str(pref))
        return sorted(set(out), key=lambda x: ipaddress.ip_network(x, strict=False).prefixlen)

    def network_info(self, ip: str) -> dict:
        data = self._get(f"network-info/data.json?resource={ip}", ttl=86400)
        d = data.get("data", {})
        asns = d.get("asns", [])
        return {
            "prefix": d.get("prefix", "") or "",
            "asn": int(asns[0]) if asns else None,
        }

    # ---------- Koku skoru ----------

    def score_asn(self, asn: int) -> dict:
        """ASN'i kokuya göre puanla. Ölü zemin -> score -1 (asla tarama)."""
        if asn in DEAD_ASNS:
            return {"asn": asn, "score": -1, "tier": "dead", "holder": "dead-asn"}
        try:
            holder = self.as_overview(asn)["holder"].lower()
        except Exception:
            return {"asn": asn, "score": 0, "tier": "unknown", "holder": "fetch-error"}
        if any(k in holder for k in DEAD_HOLDER_KEYWORDS):
            return {"asn": asn, "score": -1, "tier": "dead", "holder": holder}

        score = 10
        tier = "P2"
        if any(k in holder for k in P3_KEYWORDS):
            tier, score = "P3", 40   # residential/mobil — piyasa değeri en yüksek
        if any(k in holder for k in P1_KEYWORDS):
            tier, score = "P1", 30   # unmanaged hosting — hızlı kovan
        if any(k in holder for k in P2_KEYWORDS):
            tier = tier if tier != "P2" else "P2"
            score = max(score, 20)

        # Kardeş damar bonusu: daha önce isabet alınan ASN
        row = self.db.execute(
            "SELECT last_hit, yield_count FROM hits WHERE asn=?", (asn,)
        ).fetchone()
        if row and row[1] > 0:
            score += min(50, row[1] * 5)
            if time.time() - row[0] < 86400 * 3:
                score += 20  # son 3 günde isabet — sıcak damar

        return {"asn": asn, "score": score, "tier": tier, "holder": holder}

    def record_hit(self, asn: int, yield_count: int) -> None:
        self.db.execute(
            """INSERT INTO hits (asn, last_hit, yield_count) VALUES (?,?,1)
               ON CONFLICT(asn) DO UPDATE SET last_hit=excluded.last_hit,
               yield_count=yield_count+?""",
            (asn, time.time(), yield_count),
        )
        self.db.commit()

    # ---------- Hedef seçimi ----------

    def pick_targets(self, countries: list[str], max_asn_per_country: int = 5,
                     max_prefixes_per_asn: int = 20) -> list[dict]:
        """Ülke listesinden önceliklendirilmiş hedef paketi üret.

        Dönüş: [{"asn": int, "tier": str, "score": int, "holder": str,
                 "prefixes": [str]}] — score azalan sıralı.
        """
        candidates: list[dict] = []
        for cc in countries:
            try:
                res = self.country_resources(cc)
            except Exception:
                continue
            scored = []
            for asn in res["asn"][:200]:  # ülke başı ilk 200 ASN adayı
                s = self.score_asn(asn)
                if s["score"] > 0:
                    scored.append(s)
            scored.sort(key=lambda x: -x["score"])
            for s in scored[:max_asn_per_country]:
                try:
                    prefixes = self.announced_prefixes(s["asn"])
                except Exception:
                    continue
                if not prefixes:
                    continue
                s["prefixes"] = prefixes[:max_prefixes_per_asn]
                s["country"] = cc
                candidates.append(s)
        candidates.sort(key=lambda x: -x["score"])
        return candidates


if __name__ == "__main__":
    import sys
    countries = sys.argv[1:] or ["TR", "DE", "RU", "BR"]
    eng = TargetEngine()
    for t in eng.pick_targets(countries):
        print(f"AS{t['asn']} [{t['tier']}] score={t['score']} {t['holder'][:50]} "
              f"prefixes={len(t['prefixes'])}")
