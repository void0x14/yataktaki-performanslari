from proxy_pipeline.context.builder import ContextBuilder
from proxy_pipeline.sources.catalog import SourceCatalog, SourceMetadata
from proxy_pipeline.sources.connectors import StaticConnector, core_catalog


def test_context_builder_is_reproducible():
    builder = ContextBuilder("s1", "m1")
    assert builder.build("candidate", "c", evidence={"x": 1}).context_hash == builder.build(
        "candidate", "c", evidence={"x": 1}
    ).context_hash


def test_source_license_is_required():
    catalog = SourceCatalog()
    catalog.register(StaticConnector(SourceMetadata("fixture", "test", "static", "local", enabled=True), [{"asn": 1}]))
    assert catalog.fetch("fixture", {"asn": 1}) == [{"asn": 1}]


def test_core_sources_are_catalogued():
    names = {c.metadata.name for c in core_catalog()}
    assert {
        "rir_rdap",
        "nro_delegated",
        "bgpview",
        "ripestat",
        "routeviews",
        "ripe_ris",
        "peeringdb",
        "irr_radb",
        "rpki",
        "caida",
        "cymru",
        "geofeed",
    } <= names
