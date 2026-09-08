from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from proxy_pipeline.domain.models import ExecutionManifest, Target
from proxy_pipeline.scanners.adapter import MasscanAdapter
from proxy_pipeline.scanners.parser import L4Event


class MasscanMissing(RuntimeError):
    """masscan binary is not on PATH."""


class MasscanRunner:
    """Starts masscan and feeds list-format stdout into MasscanAdapter."""

    def __init__(self, adapter: MasscanAdapter, binary: str = "masscan") -> None:
        self.adapter = adapter
        self.binary = binary

    def command(self, manifest: ExecutionManifest, *, rate: int = 1000, extra: list[str] | None = None) -> list[str]:
        cmd = self.adapter.command_for(manifest)
        cmd[0] = self.binary
        if "-oL" not in cmd:
            cmd.extend(["-oL", "-"])
        cmd.extend(["--rate", str(rate)])
        if extra:
            cmd.extend(extra)
        return cmd

    def run(
        self,
        manifest: ExecutionManifest,
        *,
        rate: int = 1000,
        extra: list[str] | None = None,
        timeout: float | None = None,
        execute=None,
    ) -> list[L4Event]:
        cmd = self.command(manifest, rate=rate, extra=extra)
        if shutil.which(self.binary) is None and execute is None:
            raise MasscanMissing(
                f"{self.binary} yok. Kur: apt install masscan  |  veya --masscan-bin ile yolu ver."
            )
        runner = execute or subprocess.run
        completed = runner(cmd, capture_output=True, text=True, timeout=timeout)
        if getattr(completed, "returncode", 0) not in {0, None}:
            stderr = (getattr(completed, "stderr", "") or "").strip()
            raise RuntimeError(stderr or f"masscan exit {completed.returncode}")
        stdout = getattr(completed, "stdout", "") or ""
        lines = [line for line in stdout.splitlines() if line.strip() and not line.startswith("#")]
        return self.adapter.parse_stdout(manifest, lines)


def operator_manifest(cidr: str, ports: tuple[int, ...], *, decision_id: str = "operator-tara",
                      port_dizgesi: str | None = None) -> ExecutionManifest:

    profil: dict = {"source": "cli-tara"}
    if port_dizgesi:
        profil["port_dizgesi"] = port_dizgesi
    return ExecutionManifest(
        manifest_id="tara",
        decision_id=decision_id,
        targets=(Target(cidr, ports),),
        technical_profile=profil,
    )


def write_events(path: Path, events: list[L4Event]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(f"{event.target_ip} {event.port} {event.state}\n")
