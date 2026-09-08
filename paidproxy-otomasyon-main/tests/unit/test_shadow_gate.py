def test_ureten_kapi_yok_gecit_engel_degil():
    # Üretimi durduran kapı mimarisi kaldırıldı; yapay zekâ kararı akar.
    from proxy_pipeline.agents.wander import WanderAgent
    from proxy_pipeline.decision.service import DecisionService
    from proxy_pipeline.domain.models import DecisionContext
    agent = WanderAgent.__new__(WanderAgent)
    import tempfile, pathlib
    agent.journal = pathlib.Path(tempfile.mkdtemp())
    agent._seen = []
    svc = DecisionService(routes=[agent])
    ctx = DecisionContext("aday", "sentetik-1", {"cidr": "198.51.100.0/24", "scent": "squid cache hosting"}, "s", "m")
    rec = svc.decide(ctx, fresh=True)
    assert rec.decision.action.value == "sample"
