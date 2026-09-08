from proxy_pipeline.flow import seed_to_dryrun

def test_seed_to_dryrun_offline(tmp_path):
    fake = lambda ip: {"cidr": "198.51.100.0/24", "asn": 64500, "provenance": "test", "scent": "squid cache hosting"}
    out = seed_to_dryrun("198.51.100.7", lookup=fake)
    assert out["ok"] is True
    assert out["cmd"][0] == "masscan"
    assert "198.51.100.0/24" in out["cmd"]
    assert "yapay zekâ havuzu" in out["beyin"]

def test_genis_tara_komutu_yazilir():
    fake = lambda ip: {"cidr": "0.0.0.0/0", "provenance": "test", "scent": "squid cache hosting"}
    out = seed_to_dryrun("8.8.8.8", lookup=fake)
    assert out["ok"] is True
    assert "0.0.0.0/0" in out["cmd"]
