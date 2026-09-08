from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

FORBIDDEN = {"shell", "raw_sql", "unrestricted_url"}
KINDS = {
    "model_provider",
    "model_route",
    "agent_runtime",
    "agent_role",
    "tool",
    "connector",
    "prompt_pack",
    "retrieval",
    "mode_graph",
    "output_validator",
    "evaluator",
    "high_value_classifier",
}


class Plugin(Protocol):
    name: str
    version: str

    def health(self) -> bool: ...


@dataclass(frozen=True)
class PluginManifest:
    name: str
    kind: str
    version: str
    permissions: tuple[str, ...]
    config_schema: dict[str, Any]
    capability: tuple[str, ...] = ()


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, tuple[PluginManifest, Plugin]] = {}

    def register(self, manifest: PluginManifest, plugin: Plugin) -> None:
        if manifest.kind not in KINDS:
            raise ValueError(f"unsupported plugin kind: {manifest.kind}")
        if set(manifest.permissions) & FORBIDDEN:
            raise PermissionError("forbidden plugin permission")
        self._plugins[manifest.name] = (manifest, plugin)

    def healthy(self):
        return [m for m, p in self._plugins.values() if p.health()]

    def get(self, name: str) -> Plugin:
        return self._plugins[name][1]
