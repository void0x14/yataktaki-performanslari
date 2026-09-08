"""Aynı ASN'in duyurduğu prefixler (RIPEstat birincil, BGPView uyumlu ayrıştırıcı)."""
from __future__ import annotations
from proxy_pipeline.discovery.http_json import get_json

RIPESTAT = "https://stat.ripe.net/data/announced-prefixes/data.json"
BGPVIEW_API = "https://api.bgpview.io/asn/"

def parse_bgpview(payload: dict) -> dict:
    data = payload.get("data", {}) or {}
    v4 = [p.get("prefix") for p in (data.get("ipv4_prefixes", []) or []) if p.get("prefix")]
    v6 = [p.get("prefix") for p in (data.get("ipv6_prefixes", []) or []) if p.get("prefix")]
    return {"ipv4": v4, "ipv6": v6, "count": len(v4) + len(v6),
            "provenance": "bgpview:api.bgpview.io"}

def parse_ripestat(payload: dict) -> dict:
    data = payload.get("data", {}) or {}
    v4, v6 = [], []
    for p in data.get("prefixes", []) or []:
        pref = p.get("prefix") if isinstance(p, dict) else p
        if not pref:
            continue
        (v6 if ":" in str(pref) else v4).append(str(pref))
    return {"ipv4": v4, "ipv6": v6, "count": len(v4) + len(v6),
            "provenance": "ripestat:stat.ripe.net"}

def sibling_prefixes(asn: int, timeout: float = 20.0) -> dict:
    from proxy_pipeline.yuruyus import kaydet
    kaydet("kardeş-arama", f"AS{int(asn)}", "duyurular taranıyor")
    cikti = parse_ripestat(get_json(f"{RIPESTAT}?resource=AS{int(asn)}", timeout=timeout,
                                    headers={"Accept": "application/json"}))
    kaydet("kardeş", f"AS{int(asn)}", f"{cikti['count']} aralık")
    return cikti
