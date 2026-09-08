from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import ipaddress


class AssetClass(StrEnum):
    STATIC_EGRESS = "STATIC_EGRESS"
    POSSIBLE_ROTATION = "POSSIBLE_ROTATION"
    CONFIRMED_ROTATION = "CONFIRMED_ROTATION"
    MULTI_EGRESS = "MULTI_EGRESS"
    IPV6_EGRESS = "IPV6_EGRESS"
    RESIDENTIAL_LIKELY = "RESIDENTIAL_LIKELY"
    DATACENTER_LIKELY = "DATACENTER_LIKELY"
    CAPACITY_VALIDATED = "CAPACITY_VALIDATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class Assessment:
    classification: AssetClass
    confidence: str
    sample_size: int
    window_ms: int
    unique_exits: int
    evidence: tuple[str, ...]
    classifier_version: str
    diversity: dict | None = None


def classify(
    exit_ips: list[str],
    *,
    ipv6: bool = False,
    residential_signal: bool = False,
    datacenter_signal: bool = False,
    capacity_ok: bool = False,
    profile_version: str = "1",
    window_ms: int = 0,
) -> Assessment:
    unique = len(set(exit_ips))
    sample = len(exit_ips)
    versions = {ipaddress.ip_address(ip).version for ip in exit_ips if ip}
    evidence = (f"unique_exits={unique}", f"sample={sample}")
    if sample < 1:
        return Assessment(AssetClass.INSUFFICIENT_EVIDENCE, "low", sample, window_ms, unique, evidence, profile_version)
    if capacity_ok:
        cls = AssetClass.CAPACITY_VALIDATED
    elif ipv6 or 6 in versions:
        cls = AssetClass.IPV6_EGRESS
    elif unique > 1 and sample >= 3:
        cls = AssetClass.CONFIRMED_ROTATION
    elif unique > 1:
        cls = AssetClass.POSSIBLE_ROTATION if sample < 3 else AssetClass.MULTI_EGRESS
    elif residential_signal:
        cls = AssetClass.RESIDENTIAL_LIKELY
    elif datacenter_signal:
        cls = AssetClass.DATACENTER_LIKELY
    else:
        cls = AssetClass.STATIC_EGRESS
    confidence = "high" if unique > 1 and sample >= 3 else ("medium" if sample >= 2 else "low")
    return Assessment(
        cls,
        confidence,
        sample,
        window_ms,
        unique,
        evidence,
        profile_version,
        diversity={"unique_exits": unique, "ip_versions": sorted(versions)},
    )
