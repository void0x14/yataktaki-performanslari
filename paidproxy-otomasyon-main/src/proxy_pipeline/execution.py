from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic, sleep
from typing import Any, Callable


@dataclass(frozen=True)
class ExecutionProfile:
    name: str
    connect_timeout_ms: int
    handshake_timeout_ms: int
    total_timeout_ms: int
    max_attempts: int
    concurrency: int
    retryable_errors: tuple[str, ...] = ()
    backoff_ms: int = 0
    jitter_ms: int = 0
    circuit_breaker_errors: int = 0
    protocol_order: tuple[str, ...] = ()


class RateLimitBucket:
    def __init__(self, capacity: float, refill_per_second: float, key: str = "global") -> None:
        if capacity <= 0 or refill_per_second < 0:
            raise ValueError("invalid bucket")
        self.key = key
        self.capacity = capacity
        self.tokens = capacity
        self.refill = refill_per_second
        self.updated = monotonic()
        self.retry_after: float | None = None

    def consume(self, amount: float = 1) -> bool:
        now = monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.refill)
        self.updated = now
        if self.retry_after and now < self.retry_after:
            return False
        if self.tokens < amount:
            return False
        self.tokens -= amount
        return True

    def honor_retry_after(self, seconds: float) -> None:
        self.retry_after = monotonic() + seconds


class CircuitBreaker:
    def __init__(self, threshold: int = 5) -> None:
        self.threshold = threshold
        self.failures = 0
        self.open = False

    def record(self, ok: bool) -> None:
        if ok:
            self.failures = 0
            self.open = False
            return
        self.failures += 1
        if self.failures >= self.threshold:
            self.open = True

    def check(self) -> None:
        if self.open:
            raise RuntimeError("circuit breaker open")


class TechnicalExecutor:
    """Runs only caller-supplied work; semantic target selection stays outside this layer."""

    def __init__(self, profile: ExecutionProfile, bucket: RateLimitBucket | None = None, breaker: CircuitBreaker | None = None) -> None:
        self.profile = profile
        self.bucket = bucket
        self.breaker = breaker or CircuitBreaker(profile.circuit_breaker_errors or 10**9)

    def run(self, work: Callable[[], Any]) -> Any:
        self.breaker.check()
        last_exc: Exception | None = None
        for attempt in range(self.profile.max_attempts):
            if self.bucket and not self.bucket.consume():
                raise RuntimeError("rate limit bucket exhausted")
            try:
                result = work()
                self.breaker.record(True)
                return result
            except Exception as exc:
                last_exc = exc
                retryable = not self.profile.retryable_errors or exc.__class__.__name__ in self.profile.retryable_errors or str(exc) in self.profile.retryable_errors
                self.breaker.record(False)
                if attempt + 1 == self.profile.max_attempts or not retryable:
                    raise
                if self.profile.backoff_ms:
                    sleep(self.profile.backoff_ms / 1000)
        raise RuntimeError(f"execution failed: {last_exc}")


class RateLimitRegistry:
    def __init__(self) -> None:
        self.buckets: dict[str, RateLimitBucket] = {}

    def register(self, key: str, capacity: float, refill_per_second: float) -> RateLimitBucket:
        bucket = RateLimitBucket(capacity, refill_per_second, key)
        self.buckets[key] = bucket
        return bucket

    def consume(self, *keys: str) -> bool:
        return all(self.buckets[key].consume() for key in keys if key in self.buckets)

