"""Başlangıç adresi -> hedef akışı (pencereden çağrılır, testli)."""
from __future__ import annotations

def resolve_seed_to_targets(ip: str, lookup=None) -> dict:
    from proxy_pipeline.discovery.seed import lookup_seed_ip
    fn = lookup or lookup_seed_ip
    info = fn(ip.strip())
    cidr = str(info.get("cidr") or "").strip()
    if not cidr or "/" not in cidr:
        return {"ok": False, "reason": f"range bulunamadı ({info.get('provenance', '?')})", "info": info}
    targets = [{"cidr": cidr, "ports": [8080, 3128, 1080, 8888], "protocols": ["http_connect", "socks5"]}]
    if info.get("asn"):
        targets[0]["asn"] = info["asn"]
    return {"ok": True, "targets": targets, "info": info}
