from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event


@dataclass
class KillSwitch:
    active: bool = False
    reason: str = ""
    event: Event = field(default_factory=Event)

    def trigger(self, reason: str) -> None:
        self.active = True
        self.reason = reason
        self.event.set()

    def clear(self) -> None:
        self.active = False
        self.reason = ""
        self.event.clear()

    def check(self) -> None:
        if self.active:
            raise RuntimeError(f"kill switch active: {self.reason}")


class RunGate:
    """Yalnız sert şalter: yapay zekâ akarken istersen anında durdurur."""

    def __init__(self, kill_switch: KillSwitch | None = None) -> None:
        self.kill_switch = kill_switch or KillSwitch()

    def check_manifest(self, manifest) -> bool:
        self.kill_switch.check()
        return True
