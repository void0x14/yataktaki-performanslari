from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any, Protocol


@dataclass
class SourceMetadata:
    name: str
    source_type: str
    connector: str
    license_note: str
    capability: tuple[str, ...] = ()
    quota: dict[str, Any] = field(default_factory=dict)
    freshness_ms: int | None = None
    health: str = "unknown"
    enabled: bool = False
    rate_limit_remaining: int | None = None
    last_error: str | None = None
    information_gain: float | None = None
    conflict_rate: float | None = None


class DiscoveryConnector(Protocol):
    metadata: SourceMetadata

    def fetch(self, query: dict[str, Any]) -> list[dict[str, Any]]: ...

    def health_check(self) -> bool: ...


class SourceCatalog:
    """Technical access, quota and license boundaries only. No source ranking."""

    def __init__(self) -> None:
        self._sources: dict[str, DiscoveryConnector] = {}

    def register(self, connector: DiscoveryConnector) -> None:
        if not connector.metadata.license_note:
            raise ValueError("source license must be explicit")
        self._sources[connector.metadata.name] = connector

    def enabled(self) -> list[DiscoveryConnector]:
        return [x for x in self._sources.values() if x.metadata.enabled]

    def describe(self) -> list[SourceMetadata]:
        return [x.metadata for x in self._sources.values()]

    def get(self, name: str) -> DiscoveryConnector:
        return self._sources[name]

    def fetch(self, name: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        source = self._sources[name]
        if not source.metadata.enabled:
            raise PermissionError(f"source disabled: {name}")
        try:
            result = source.fetch(query)
            source.metadata.health = "healthy"
            source.metadata.freshness_ms = int(time() * 1000)
            source.metadata.last_error = None
            return result
        except Exception as exc:
            source.metadata.health = "unhealthy"
            source.metadata.last_error = str(exc)
            raise
