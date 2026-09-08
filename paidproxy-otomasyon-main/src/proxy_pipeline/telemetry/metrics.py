from __future__ import annotations

from collections import Counter
import time


class Metrics:
    def __init__(self) -> None:
        self.counters: Counter = Counter()
        self.gauges: dict[str, float] = {}
        self.started = time.monotonic()

    def inc(self, name: str, value: int = 1) -> None:
        self.counters[name] += value

    def gauge(self, name: str, value: float) -> None:
        self.gauges[name] = value

    def snapshot(self) -> dict:
        return {
            **self.counters,
            **{f"gauge.{k}": v for k, v in self.gauges.items()},
            "uptime_seconds": round(time.monotonic() - self.started, 3),
        }

    def prometheus(self) -> str:
        lines = [f"proxy_pipeline_{k} {v}" for k, v in sorted(self.counters.items())]
        lines.extend(f"proxy_pipeline_gauge_{k} {v}" for k, v in sorted(self.gauges.items()))
        lines.append(f"proxy_pipeline_uptime_seconds {round(time.monotonic() - self.started, 3)}")
        return "\n".join(lines) + "\n"
