from __future__ import annotations

from collections import Counter

from proxy_pipeline.domain.events import EVENT_TYPES, Event


class EventBus:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.counts: Counter = Counter()

    def publish(self, event: Event) -> None:
        if event.event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {event.event_type}")
        self.events.append(event)
        self.counts[event.event_type] += 1

    def by_type(self, event_type: str) -> list[Event]:
        return [e for e in self.events if e.event_type == event_type]
