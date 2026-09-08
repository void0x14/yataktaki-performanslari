from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WatermarkProfile:
    name: str
    spool_pause_bytes: int
    spool_slow_bytes: int
    writer_lag_ms: int
    fd_limit: int
    cpu_lag_ms: int


class BackpressureController:
    """Technical speed control only. Never produces target priority."""

    def __init__(self, profile: WatermarkProfile) -> None:
        self.profile = profile
        self.paused = False
        self.slowed = False

    def observe(self, *, spool_bytes: int = 0, writer_lag_ms: int = 0, fd_used: int = 0, cpu_lag_ms: int = 0) -> str:
        if spool_bytes >= self.profile.spool_pause_bytes or writer_lag_ms >= self.profile.writer_lag_ms * 4:
            self.paused = True
            self.slowed = True
            return "pause"
        if spool_bytes >= self.profile.spool_slow_bytes or writer_lag_ms >= self.profile.writer_lag_ms or fd_used >= self.profile.fd_limit:
            self.paused = False
            self.slowed = True
            return "slow"
        self.paused = False
        self.slowed = False
        return "run"
