from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
from uuid import uuid4

from proxy_pipeline.domain.time import utc_epoch_ms


@dataclass(frozen=True)
class L4Event:
    target_ip: str
    port: int
    state: str
    scanner_metadata: dict
    schema_version: str = "1"
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp_ms: int = field(default_factory=utc_epoch_ms)
    decision_id: str = ""
    manifest_id: str = ""
    scan_run_id: str = ""
    segment_id: str = ""
    asn: int | None = None
    prefix: str | None = None
    correlation_id: str = ""
    causation_id: str = ""

    @property
    def idempotency_key(self) -> str:
        return f"{self.target_ip}:{self.port}:{self.state}:{self.manifest_id}"


class MasscanParser:
    """Parses only Masscan list output; it never launches a scanner."""

    def parse_line(self, line: str, **ids) -> L4Event:
        parts = line.strip().split()
        if len(parts) < 4 or parts[0] != "open":
            raise ValueError("malformed masscan line")
        proto, port, ip = parts[1], int(parts[2]), parts[3]
        ipaddress.ip_address(ip)
        if proto.lower() != "tcp" or not 1 <= port <= 65535:
            raise ValueError("invalid scanner event")
        return L4Event(ip, port, "OPEN", {"protocol": proto.lower()}, **ids)
