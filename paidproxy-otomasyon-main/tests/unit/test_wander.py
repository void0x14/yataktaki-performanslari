from proxy_pipeline.agents.wander import WanderAgent
from proxy_pipeline.domain.models import DecisionContext

def test_wander_research_without_evidence(tmp_path):
    a = WanderAgent(journal=tmp_path)
    ctx = DecisionContext("aday", "roam-1", {}, "s1", "m1")
    out = a.decide(ctx)
    assert out["action"] == "research"
    assert out["items"][0]["candidate_id"] == "roam-1"
    assert (tmp_path / f"gunluk-{__import__('datetime').datetime.now().strftime('%Y%m%d')}.md").exists()

def test_wander_samples_with_cidr(tmp_path):
    a = WanderAgent(journal=tmp_path)
    ctx = DecisionContext("aday", "as1", {
        "cidr": "198.51.100.0/24",
        "scent": "unutulmuş squid cache / hosting bloğu",
        "provenance": "bgp.he.net",
    }, "s1", "m1")
    out = a.decide(ctx)
    assert out["action"] == "sample"
    assert out["targets"][0]["cidr"] == "198.51.100.0/24"
    assert out["targets"][0]["ports"] == [3128]
    assert out["first_port"] == 3128
    assert "squid" in out["first_port_reason"].lower()


def test_wander_does_not_bite_a_cidr_without_scent(tmp_path):
    a = WanderAgent(journal=tmp_path)
    ctx = DecisionContext("aday", "cold-1", {"cidr": "198.51.100.0/24"}, "s1", "m1")
    out = a.decide(ctx)
    assert out["action"] == "research"
    assert out["targets"] == []
    assert "koku" in out["reason"].lower()


def test_wander_uses_socks_scent_for_single_first_port(tmp_path):
    a = WanderAgent(journal=tmp_path)
    ctx = DecisionContext("aday", "cpe-1", {
        "cidr": "198.51.100.0/24",
        "org": "broadband PPPoE CPE",
        "scent": "açık SOCKS / MikroTik kokusu",
        "provenance": "rdap",
    }, "s1", "m1")
    out = a.decide(ctx)
    assert out["action"] == "sample"
    assert out["targets"][0]["ports"] == [1080]
    assert out["first_port"] == 1080
