from proxy_pipeline.wander_loop import run_tour

def test_tour_offline(tmp_path):
    snaps = [{"candidate_id": "a1", "cidr": "198.51.100.0/24", "scent": "squid cache hosting"},
             {"candidate_id": "a2"}]
    out = run_tour(snaps, journal=tmp_path)
    assert [r["candidate_id"] for r in out] == ["a1", "a2"]
    assert out[0]["action"] == "sample"
    assert out[1]["action"] == "research"
    assert list(tmp_path.glob("gunluk-*.md"))
