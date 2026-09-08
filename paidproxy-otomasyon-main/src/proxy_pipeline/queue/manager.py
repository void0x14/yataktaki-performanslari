from __future__ import annotations

from dataclasses import dataclass
from time import time

from proxy_pipeline.domain.states import SegmentState
from proxy_pipeline.queue.segments import Segment


@dataclass
class Lease:
    segment_id: str
    owner: str
    until_ms: int


class SegmentQueue:
    def __init__(self) -> None:
        self._segments: dict[str, Segment] = {}
        self._leases: dict[str, Lease] = {}

    def add(self, segment: Segment) -> None:
        if segment.segment_id in self._segments:
            raise ValueError("duplicate segment")
        if segment.state == SegmentState.CREATED.value:
            segment.state = SegmentState.READY.value
        self._segments[segment.segment_id] = segment

    def get(self, segment_id: str) -> Segment:
        return self._segments[segment_id]

    def lease(self, owner: str, ttl_ms: int) -> Segment | None:
        now = int(time() * 1000)
        for segment in self._segments.values():
            lease = self._leases.get(segment.segment_id)
            if segment.state in {SegmentState.CREATED.value, SegmentState.READY.value, SegmentState.PARTIAL.value} and (
                lease is None or lease.until_ms <= now
            ):
                item = Lease(segment.segment_id, owner, now + ttl_ms)
                self._leases[segment.segment_id] = item
                segment.state = SegmentState.LEASED.value
                segment.lease_owner = owner
                segment.lease_until = item.until_ms
                segment.checkpoint()
                return segment
        return None

    def release(self, segment_id: str, *, completed: bool = False, failed: bool = False) -> None:
        segment = self._segments[segment_id]
        self._leases.pop(segment_id, None)
        if completed:
            segment.state = SegmentState.COMPLETED.value
        elif failed:
            segment.state = SegmentState.FAILED.value
            segment.retry_count += 1
        else:
            segment.state = SegmentState.PARTIAL.value
        segment.checkpoint()

    def ready(self) -> list[Segment]:
        return [s for s in self._segments.values() if s.state == SegmentState.READY.value]
