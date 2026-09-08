from proxy_pipeline.discovery.seed import parse_rdap

def test_parse_rdap_offline():
    payload = {"cidr": "198.51.100.0/24",
               "entities": [{"handle": ["AS64500"]}],
               "remarks": [{"description": ["Ornek Sahibi"] }]}
    out = parse_rdap(payload, "https://rdap.db.ripe.net/ip/")
    assert out["cidr"] == "198.51.100.0/24"
    assert out["asn"] == 64500
    assert out["org"] == "Ornek Sahibi"
    assert out["provenance"].startswith("rdap:")

def test_lookup_rejects_bad_ip():
    from proxy_pipeline.discovery.seed import lookup_seed_ip
    import pytest
    with pytest.raises(ValueError):
        lookup_seed_ip("degil-bir-ip")
