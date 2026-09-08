from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelRoute:
    role: str
    provider: str
    model: str
    version: str
    fallback_order: int = 0
    config: dict[str, Any] = field(default_factory=dict)
    healthy: bool = True
    capability: str = "decision"


class RouteRegistry:
    def __init__(self) -> None:
        self._routes: list[ModelRoute] = []

    def register(self, route: ModelRoute) -> None:
        self._routes.append(route)

    def for_role(self, role: str, capability: str = "decision") -> list[ModelRoute]:
        return sorted(
            (x for x in self._routes if x.role == role and x.healthy and x.capability == capability),
            key=lambda x: x.fallback_order,
        )

    def set_health(self, provider: str, healthy: bool) -> None:
        for route in self._routes:
            if route.provider == provider:
                route.healthy = healthy
