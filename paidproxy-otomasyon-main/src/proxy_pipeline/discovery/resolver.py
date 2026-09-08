from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Organization:
    canonical_name: str
    aliases: tuple[str, ...]
    confidence: float
    country: str | None = None
    network_role: str | None = None


class EntityResolver:
    def __init__(self) -> None:
        self._aliases: dict[str, str] = {}

    def resolve(self, name: str) -> Organization:
        key = " ".join(name.lower().split())
        canonical = self._aliases.get(key, key)
        aliases = tuple(k for k, v in self._aliases.items() if v == canonical)
        return Organization(canonical, aliases, 1.0 if key in self._aliases else 0.5)

    def register_alias(self, alias: str, canonical: str) -> None:
        self._aliases[" ".join(alias.lower().split())] = " ".join(canonical.lower().split())
