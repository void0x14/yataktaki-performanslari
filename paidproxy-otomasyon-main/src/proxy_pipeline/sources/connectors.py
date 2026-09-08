from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from proxy_pipeline.sources.catalog import SourceMetadata


@dataclass
class StaticConnector:
    metadata: SourceMetadata
    records: list[dict]

    def fetch(self, query: dict) -> list[dict]:
        return [r for r in self.records if all(r.get(k) == v for k, v in query.items())]

    def health_check(self) -> bool:
        return True


CORE_SOURCES = (
    ("rir_rdap", "rir", "rdap", "RIR RDAP public allocation data", ("allocation", "organization", "prefix")),
    ("nro_delegated", "rir", "nro", "NRO delegated statistics", ("allocation", "prefix")),
    ("bgpview", "bgp", "bgpview", "BGPView announced prefixes", ("prefix", "asn", "upstream")),
    ("ripestat", "bgp", "ripestat", "RIPEstat routing status", ("prefix", "asn", "history")),
    ("routeviews", "bgp", "routeviews", "RouteViews BGP table dumps", ("prefix", "origin")),
    ("ripe_ris", "bgp", "ris", "RIPE RIS BGP updates", ("prefix", "origin")),
    ("peeringdb", "operator", "peeringdb", "PeeringDB network declarations", ("network_type", "facility")),
    ("irr_radb", "irr", "radb", "IRR/RADB route objects", ("route", "route6", "mntner")),
    ("rpki", "rpki", "rpki", "RPKI ROA authorizations", ("roa", "origin")),
    ("caida", "graph", "caida", "CAIDA AS rank/org/relationships", ("as_rank", "as_org", "as_rel")),
    ("cymru", "asn", "cymru", "Team Cymru IP-to-ASN", ("ip_to_asn",)),
    ("geofeed", "geo", "geofeed", "Regional delegated and geofeed records", ("geo",)),
)


def core_catalog(enabled: bool = False) -> list[StaticConnector]:
    connectors = []
    for name, source_type, connector, license_note, capability in CORE_SOURCES:
        connectors.append(
            StaticConnector(
                SourceMetadata(
                    name=name,
                    source_type=source_type,
                    connector=connector,
                    license_note=license_note,
                    capability=capability,
                    enabled=enabled,
                ),
                records=[],
            )
        )
    return connectors
