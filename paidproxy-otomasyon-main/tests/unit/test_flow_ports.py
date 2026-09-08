from proxy_pipeline.flow import seed_to_dryrun, mark_high_ports

def test_mark_high_ports_display_only():
    m = mark_high_ports([3128, 8080, 8888])
    assert m["high"] == [8080, 8888]
    assert m["all"] == [3128, 8080, 8888]

def test_flow_includes_ports(tmp_path):
    fake = lambda ip: {"cidr": "198.51.100.0/24", "provenance": "test", "scent": "squid cache hosting"}
    out = seed_to_dryrun("198.51.100.7", lookup=fake)
    assert out["ok"] is True and "ports" in out
