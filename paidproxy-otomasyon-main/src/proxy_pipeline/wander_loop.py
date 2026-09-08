"""Gezgin turu: aday listesinde Aşama-1 sentez turu. Tarama YOK, yalnızca observe+decide."""
from __future__ import annotations
from pathlib import Path

def run_tour(snapshots: list, journal=None) -> list:
    from proxy_pipeline.agents.select import select_routes
    from proxy_pipeline.agents.wander import WanderAgent
    from proxy_pipeline.decision.service import DecisionService
    from proxy_pipeline.domain.models import DecisionContext
    from proxy_pipeline.yuruyus import kaydet as iz_kaydet
    iz_kaydet("tur-başlangıç", f"{len(snapshots)} aday", "gezinme turu")
    yollar, beyin, _yedek = select_routes(journal=journal)
    # tur gözleri her zaman iz bırakır; karar yerleşik beyindendir
    agent = next((r for r in yollar if isinstance(r, WanderAgent)), None)
    if agent is None:
        agent = WanderAgent(journal=journal) if journal else WanderAgent()
    svc = DecisionService(routes=yollar)
    out = []
    for i, snap in enumerate(snapshots):
        cid = str(snap.get("candidate_id", f"tur-{i}"))
        agent.observe(f"tur gözlemi: {snap}", cid)
        ctx = DecisionContext("aday", cid, snap, "tur-s", "tur-m")
        try:
            rec = svc.decide(ctx, fresh=True)
            out.append({"candidate_id": cid, "action": rec.decision.action.value if rec.decision else "none", "beyin": beyin})
        except Exception as e:
            out.append({"candidate_id": cid, "action": f"bloklandi:{e}"})
    agent.observe(f"tur sentezi: {len(out)} aday gezildi", "sentez")
    return out
