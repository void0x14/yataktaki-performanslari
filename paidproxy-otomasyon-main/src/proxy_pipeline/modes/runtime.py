from __future__ import annotations

from dataclasses import dataclass

from proxy_pipeline.modes.registry import ModeRegistry


@dataclass(frozen=True)
class RuntimeMode:
    name: str
    version: str
    mode_type: str


class ModeRuntime:
    def __init__(self, registry: ModeRegistry) -> None:
        self.registry = registry
        self.current: RuntimeMode | None = None

    def activate_at_checkpoint(self, name: str) -> RuntimeMode:
        mode = self.registry.get(name)
        self.registry.activate(name)
        self.current = RuntimeMode(mode.name, mode.version, mode.mode_type)
        return self.current

    def rollback(self) -> RuntimeMode:
        self.registry.rollback()
        mode = self.registry.get()
        self.current = RuntimeMode(mode.name, mode.version, mode.mode_type)
        return self.current
