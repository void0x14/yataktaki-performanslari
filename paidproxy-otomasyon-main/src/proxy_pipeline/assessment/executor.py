from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from proxy_pipeline.assessment.classifier import Assessment, classify


@dataclass(frozen=True)
class TestProfile:
    __test__ = False
    name: str
    version: str
    samples: int
    window_ms: int
    regions: tuple[str, ...]
    capacity_enabled: bool = False
    operator_capacity_ack: bool = False


class HighValueExecutor:
    """Deterministic deep-test runner. AI chooses who is tested; this layer only measures."""

    def __init__(self, profile: TestProfile, echo: Callable[[str], str]) -> None:
        self.profile = profile
        self.echo = echo

    def run(self, endpoint: str) -> Assessment:
        if self.profile.capacity_enabled and not self.profile.operator_capacity_ack:
            raise PermissionError("capacity tests require explicit operator approval")
        exits = [self.echo(endpoint) for _ in range(self.profile.samples)]
        return classify(
            exits,
            profile_version=self.profile.version,
            window_ms=self.profile.window_ms,
            capacity_ok=self.profile.capacity_enabled and self.profile.operator_capacity_ack,
        )
