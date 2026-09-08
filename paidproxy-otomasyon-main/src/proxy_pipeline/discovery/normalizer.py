from __future__ import annotations

from dataclasses import dataclass
import ipaddress


@dataclass(frozen=True)
class NormalizedPrefix:
    network: str
    prefix_length: int
    ip_version: int
    origin_asn: int | None
    source_name: str
    observed_at: int
    payload_hash: str
    cidr: str = ""


def normalize_prefix(record: dict, source_name: str, observed_at: int, payload_hash: str) -> NormalizedPrefix:
    network = ipaddress.ip_network(record["prefix"], strict=False)
    asn = record.get("origin_asn")
    if asn is not None:
        asn = int(str(asn).removeprefix("AS"))
    return NormalizedPrefix(
        str(network.network_address),
        network.prefixlen,
        network.version,
        asn,
        source_name,
        observed_at,
        payload_hash,
        str(network),
    )


def normalize_asn(value: str | int) -> int:
    return int(str(value).upper().removeprefix("AS"))
