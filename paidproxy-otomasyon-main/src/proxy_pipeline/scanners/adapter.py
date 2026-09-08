from __future__ import annotations

import ipaddress
from typing import Iterable

from proxy_pipeline.queue.spool import AppendOnlySpool
from proxy_pipeline.safety import RunGate
from proxy_pipeline.scanners.parser import L4Event, MasscanParser


class MasscanAdapter:
    """Manifest-bound adapter. Process startup is deliberately injected by the caller."""

    def __init__(self, gate: RunGate, parser: MasscanParser | None = None, dead_letter: AppendOnlySpool | None = None) -> None:
        self.gate = gate
        self.parser = parser or MasscanParser()
        self.dead_letter = dead_letter

    @staticmethod
    def _araliklar(manifest) -> list:
        dizge = (getattr(manifest, "technical_profile", {}) or {}).get("port_dizgesi", "")
        bantlar = []
        for parc in str(dizge).split(","):
            parc = parc.strip()
            if "-" in parc:
                try:
                    a, b = parc.split("-", 1)
                    bantlar.append((int(a), int(b)))
                except ValueError:
                    continue
        return bantlar

    def _izinli(self, manifest, port: int) -> bool:
        bantlar = self._araliklar(manifest)
        if bantlar:
            return any(a <= port <= b for a, b in bantlar)
        return port in {p for target in manifest.targets for p in target.ports}

    def parse_stdout(self, manifest, lines: Iterable[str], **ids) -> list[L4Event]:
        self.gate.check_manifest(manifest)
        networks = [ipaddress.ip_network(target.cidr, strict=False) for target in manifest.targets]
        events: list[L4Event] = []
        for line in lines:
            try:
                event = self.parser.parse_line(
                    line,
                    decision_id=getattr(manifest, "decision_id", ""),
                    manifest_id=getattr(manifest, "manifest_id", ""),
                    **ids,
                )
            except ValueError:
                if self.dead_letter is not None:
                    self.dead_letter.append(line.strip())
                else:
                    raise
                continue
            addr = ipaddress.ip_address(event.target_ip)
            if not self._izinli(manifest, event.port):
                raise ValueError("scanner event port is outside manifest")
            if not any(addr in network for network in networks):
                raise ValueError("scanner event ip is outside manifest")
            events.append(event)
        return events

    def command_for(self, manifest) -> list[str]:
        self.gate.check_manifest(manifest)
        ranges = ",".join(target.cidr for target in manifest.targets)
        dizge = (getattr(manifest, "technical_profile", {}) or {}).get("port_dizgesi", "")
        ports = dizge.strip() or ",".join(str(port) for target in manifest.targets for port in target.ports)
        return ["masscan", ranges, "-p", ports, "--wait", "0"]
