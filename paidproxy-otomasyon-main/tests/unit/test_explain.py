from proxy_pipeline.flow import seed_to_dryrun

def test_flow_carries_why_card(tmp_path):
    fake = lambda ip: {"cidr": "198.51.100.0/24", "asn": 64500, "provenance": "test", "scent": "squid cache hosting"}
    out = seed_to_dryrun("198.51.100.7", lookup=fake)
    assert out["ok"] is True
    assert "198.51.100.0/24" in (out["why"] or "")
    assert out["confidence"]
    assert out["evidence"] and out["risks"]
