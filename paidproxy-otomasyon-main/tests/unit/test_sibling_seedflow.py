from proxy_pipeline.discovery.sibling import parse_bgpview
from proxy_pipeline.discovery.seed_flow import resolve_seed_to_targets

def test_parse_bgpview_offline():
    payload = {"data": {"ipv4_prefixes": [{"prefix": "198.51.100.0/24"}], "ipv6_prefixes": []}}
    out = parse_bgpview(payload)
    assert out["ipv4"] == ["198.51.100.0/24"]
    assert out["count"] == 1

def test_seed_flow_uses_lookup():
    fake = lambda ip: {"cidr": "198.51.100.0/24", "asn": 64500, "provenance": "test"}
    out = resolve_seed_to_targets("198.51.100.7", lookup=fake)
    assert out["ok"] is True
    assert out["targets"][0]["asn"] == 64500

def test_seed_flow_range_yoksa():
    fake = lambda ip: {"cidr": "tekil", "provenance": "test"}
    out = resolve_seed_to_targets("1.2.3.4", lookup=fake)
    assert out["ok"] is False

def test_parse_ripestat_offline():
    from proxy_pipeline.discovery.sibling import parse_ripestat
    payload = {"data": {"prefixes": [{"prefix": "1.1.1.0/24"}, {"prefix": "2606:4700::/32"}]}}
    out = parse_ripestat(payload)
    assert out["ipv4"] == ["1.1.1.0/24"]
    assert out["ipv6"] == ["2606:4700::/32"]
