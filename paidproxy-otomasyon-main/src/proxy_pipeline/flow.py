"""Başlangıç -> yapay zekâ kararı -> kuru-tarama uç akışı. Gerçek tarama YOK."""
from __future__ import annotations
from pathlib import Path


def mark_high_ports(ports) -> dict:
    """Görüntüleme yardımcısı (karar DEĞİL): yüksek portları işaretler."""
    ps = [int(x) for x in ports]
    return {"all": ps, "high": sorted(x for x in ps if x >= 8000),
            "note": "yüksek-port vurgusu yalnızca görüntü içindir; port seçimi AI kararındandır"}

def seed_to_dryrun(ip: str, *, lookup=None) -> dict:
    from proxy_pipeline.discovery.seed_flow import resolve_seed_to_targets
    from proxy_pipeline.agents.select import select_routes
    from proxy_pipeline.decision.service import DecisionService
    from proxy_pipeline.domain.models import DecisionContext
    from proxy_pipeline.safety import KillSwitch, RunGate
    from proxy_pipeline.scanners.adapter import MasscanAdapter
    from proxy_pipeline.scanners.runner import MasscanRunner, operator_manifest
    from proxy_pipeline.yuruyus import kaydet as iz_kaydet
    iz_kaydet("akış-başlangıç", ip, "başlangıçtan kuru komuta")
    res = resolve_seed_to_targets(ip, lookup=lookup)
    if not res.get("ok"):
        return {"ok": False, "reason": res.get("reason")}
    seed_cidr = res["targets"][0]["cidr"]
    routes, beyin, _ = select_routes()
    svc = DecisionService(routes=routes)
    discovery_snapshot = dict(res.get("info") or {})
    discovery_snapshot.update({"cidr": seed_cidr, "seed_ip": ip,
                               "provenance": discovery_snapshot.get("provenance", "seed")})
    ctx = DecisionContext("aday", f"seed-{ip}", discovery_snapshot, "flow-s", "flow-m")
    rec = svc.decide(ctx, fresh=True)
    dec = rec.decision
    tgts = [(t.cidr, tuple(t.ports)) for t in dec.targets] if dec else []
    if not tgts or not tgts[0][1]:
        return {"ok": True, "decision": dec.action.value if dec else "research",
                "note": "taranacak hedef/ilk diş yok (research)", "cmd": None, "beyin": beyin,
                "why": dec.expected_value if dec else "AI kararı yok",
                "evidence": list(dec.evidence) if dec else [],
                "counter": list(dec.counter_evidence) if dec else []}
    cidr, ports = tgts[0]
    man = operator_manifest(cidr, tuple(int(p) for p in ports))
    KillSwitch().check()
    cmd = MasscanRunner(MasscanAdapter(RunGate())).command(man, rate=1000)
    marked = [(c, mark_high_ports(ps)) for c, ps in tgts]
    return {"ok": True, "decision": dec.action.value, "targets": tgts, "ports": marked,
            "why": dec.expected_value, "confidence": dec.confidence,
            "evidence": list(dec.evidence), "counter": list(dec.counter_evidence),
            "cmd": cmd, "beyin": beyin,
            "risks": list(dec.risks)}
