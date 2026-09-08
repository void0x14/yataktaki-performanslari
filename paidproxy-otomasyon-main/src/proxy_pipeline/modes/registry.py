from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModeManifest:
    name: str
    mode_type: str
    version: str
    graph: dict[str, Any]
    enabled: bool = True
    activation: str = "inactive"
    created_by: str = "operator"


class ModeRegistry:
    VALID = {
        "single_agent",
        "manager_subagents",
        "router",
        "ensemble_judge",
        "debate_consensus",
        "human_in_loop",
        "external",
    }

    def __init__(self) -> None:
        self._modes: dict[str, ModeManifest] = {}
        self.active: str | None = None
        self.previous: str | None = None

    def register(self, manifest: ModeManifest) -> None:
        if manifest.mode_type not in self.VALID:
            raise ValueError("unsupported mode")
        self._modes[manifest.name] = manifest

    def activate(self, name: str) -> None:
        if name not in self._modes or not self._modes[name].enabled:
            raise KeyError(name)
        self.previous = self.active
        self.active = name

    def rollback(self) -> None:
        if not self.previous:
            raise RuntimeError("no previous mode")
        self.activate(self.previous)

    def get(self, name: str | None = None) -> ModeManifest:
        selected = name or self.active
        if not selected:
            raise RuntimeError("no mode selected")
        return self._modes[selected]

    def list(self) -> list[ModeManifest]:
        return list(self._modes.values())
