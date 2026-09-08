"""Koku ile hedef seçen açık proxy avcısı."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

JOURNAL = Path("var/journal")


def _scent_text(snapshot: dict) -> str:
    """Return observed descriptive fields used to choose the first bite."""
    fields = ("scent", "banner", "org", "organization", "notes", "observation")
    return " ".join(str(snapshot.get(key) or "") for key in fields).strip().lower()


def _first_bite(snapshot: dict) -> tuple[int | None, str]:
    """Choose one port from an observed scent, never from a universal list."""
    explicit = snapshot.get("first_port")
    explicit_reason = str(snapshot.get("first_port_reason") or "").strip()
    if explicit is not None and explicit_reason:
        try:
            port = int(explicit)
        except (TypeError, ValueError):
            port = 0
        if 1 <= port <= 65535:
            return port, explicit_reason

    scent = _scent_text(snapshot)
    if not scent:
        return None, "koku yok; ilk diş seçilmedi"
    if any(token in scent for token in ("socks", "mikrotik", "cpe", "router", "pppoe", "adsl")):
        return 1080, "SOCKS/CPE/MikroTik kokusu nedeniyle ilk diş 1080"
    if any(token in scent for token in ("http proxy", "proxy panel", "8080")):
        return 8080, "HTTP proxy/panel kokusu nedeniyle ilk diş 8080"
    if any(token in scent for token in ("squid", "cache", "forward proxy", "reseller", "colo", "hosting", "proxy")):
        return 3128, "Squid/cache/forward-proxy/hosting kokusu nedeniyle ilk diş 3128"
    return None, f"koku var ama proxy dişi çıkarılamadı: {scent[:160]}"


class WanderAgent:
    version = "yerlesik-beyin-1"

    def __init__(self, journal: Path = JOURNAL) -> None:
        self.journal = journal
        self.journal.mkdir(parents=True, exist_ok=True)
        self._seen: list[str] = []

    def observe(self, note: str, candidate_id: str = "roam") -> Path:
        day = datetime.now().strftime("%Y%m%d")
        f = self.journal / f"gunluk-{day}.md"
        line = f"- {datetime.now().isoformat(timespec='seconds')} [{candidate_id}] {note}\n"
        with f.open("a", encoding="utf-8") as h:
            h.write(line)
        self._seen.append(note)
        return f

    def decide(self, context) -> dict:
        snap = dict(getattr(context, "snapshot", {}) or {})
        cid = getattr(context, "candidate_id", "roam")
        hint = str(snap.get("baslangic_ip") or snap.get("seed_ip") or snap.get("cidr") or snap.get("asn") or cid)
        first_port, first_port_reason = _first_bite(snap)

        if (snap.get("komşu_sinyal") or snap.get("sibling_prefix")) and first_port:
            action = "sample"
            cidr = str(snap.get("sibling_prefix") or snap.get("cidr") or "")
            ports = [first_port]
        elif snap.get("cidr") and first_port:
            action = "sample"
            cidr = str(snap["cidr"])
            ports = [first_port]
        else:
            action = "research"
            cidr = ""
            ports = []

        self.observe(f"karar={action} ipuc={hint} kanit={json.dumps(snap, ensure_ascii=True)[:300]}", cid)
        targets = [{"cidr": cidr, "ports": ports, "protocols": ["http_connect", "socks5"]}] if cidr else []
        items = [{"candidate_id": cid, "action": action, "targets": targets,
                  "order_index": 0, "resource_allocation": {"addresses": int(snap.get("addresses") or 256)},
                  "stop_expression": {"when": "evidence.ready"}}]
        why = (f"{first_port_reason}; başlangıç {hint} -> {cidr}"
               if cidr else f"{first_port_reason}; aralık/ilk diş yok, araştırmaya dön: {hint}")
        return {"action": action, "targets": targets,
                "provider": self.version,
                "first_port": first_port,
                "first_port_reason": first_port_reason,
                "reason": why,
                "resource_plan": {"addresses": int(snap.get("addresses") or 256)},
                "stop_condition": {"when": "evidence.ready"},
                "evidence": [f"roam:{hint}", why, f"kaynak: {snap.get('provenance', 'bilinmiyor')}"],
                "counter_evidence": (["henüz L4/L7 kanıtı yok; değer hükmü erken olur"]
                                     if cidr else ["koku veya ilk diş yok; tarama yok"]),
                "risks": ["henüz L4/L7 kanıtı yok; değer hükmü erken olur"],
                "expected_value": why,
                "confidence": "düşük (gözlem aşaması)" if action == "research" else "orta (örnekleme aşaması)",
                "alternatives": ["erteleyip yeni koku bekle", "kanıtlı canlı hedefin kardeşine bak"],
                "items": items}
