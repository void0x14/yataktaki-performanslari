from __future__ import annotations

from dataclasses import dataclass, field

from proxy_pipeline.domain.models import ExecutionManifest
from proxy_pipeline.safety import KillSwitch


@dataclass
class Scheduler:
    """Schedules only committed manifests and technical maintenance. Never scores targets."""

    kill_switch: KillSwitch
    queue: list[ExecutionManifest] = field(default_factory=list)

    def enqueue(self, manifest: ExecutionManifest) -> None:
        self.kill_switch.check()
        if not manifest.decision_id:
            raise ValueError("scheduler refuses manifests without an AI decision id")
        if manifest.status != "committed":
            raise ValueError("scheduler accepts only committed manifests")
        self.queue.append(manifest)

    def next(self) -> ExecutionManifest | None:
        self.kill_switch.check()
        if not self.queue:
            return None
        return self.queue.pop(0)
