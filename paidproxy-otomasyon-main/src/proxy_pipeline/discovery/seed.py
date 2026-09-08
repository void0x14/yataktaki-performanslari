"""Seed IP -> owner range (RDAP, read-only). myip.ms kazıma YOK."""
from __future__ import annotations
import ipaddress
from proxy_pipeline.discovery.http_json import get_json

RDAP_URLS = [
    "https://rdap.db.ripe.net/ip/",
    "https://rdap.arin.net/registry/ip/",
    "https://rdap.apnic.net/ip/",
]

def parse_rdap(payload: dict, source: str) -> dict:
    raw = payload.get("cidr") or payload.get("handle") or ""
    cidr = range_to_cidr(raw) if " - " in str(raw) else str(raw)
    asn = None
    for ent in payload.get("entities", []) or []:
        for h in ent.get("handle", []) or []:
            s = str(h)
            if s.upper().startswith("AS"):
                try:
                    asn = int(s[2:])
                except ValueError:
                    pass
    org = ""
    for n in payload.get("remarks", []) or []:
        for d in n.get("description", []) or []:
            if d and not org:
                org = str(d)[:120]
    return {"cidr": str(cidr), "asn": asn, "org": org, "source": source,
            "provenance": f"rdap:{source}"}

def range_to_cidr(text: str) -> str:
    """'a - b' aralığını kapsayan en küçük CIDR listesinin ilkidir (tek hedef için)."""
    try:
        a, b = [x.strip() for x in str(text).split("-")]
        nets = list(ipaddress.summarize_address_range(ipaddress.ip_address(a), ipaddress.ip_address(b)))
        return str(nets[0]) if nets else str(text).strip()
    except Exception:
        return str(text).strip()

def lookup_seed_ip(ip: str, timeout: float = 10.0) -> dict:
    ipaddress.ip_address(ip)
    from proxy_pipeline.yuruyus import kaydet
    kaydet("tohum", ip, "sahiplik aranıyor")
    last = None
    for base in RDAP_URLS:
        try:
            bilgi = parse_rdap(get_json(base + ip, timeout=timeout,
                                        headers={"Accept": "application/rdap+json"}), base)
            if bilgi:
                kaydet("sahiplik", ip, str(bilgi.get("cidr")))
                return bilgi
            last = f"{base}: empty response"
        except Exception as e:
            last = f"{base}: {e}"
    raise RuntimeError(f"RDAP çözülemedi ({last})")
