from proxy_pipeline.context.aggregate import Evidence, EvidenceAggregator
from proxy_pipeline.discovery.resolver import EntityResolver


def test_evidence_snapshot_preserves_conflicts():
    result = EvidenceAggregator().snapshot(
        [Evidence("a", "role", "isp", "high", 1, "x"), Evidence("b", "role", "hosting", "medium", 2, "y")]
    )
    assert result["conflicts"]["role"] == ["hosting", "isp"]


def test_entity_resolver_aliases():
    resolver = EntityResolver()
    resolver.register_alias("Example Networks LLC", "Example")
    assert resolver.resolve("Example Networks LLC").canonical_name == "example"
