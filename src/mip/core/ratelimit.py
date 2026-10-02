"""Token bucket per source and identity, jittered exponential backoff, circuit breaker."""

import random
import threading
import time

from mip.core.types import RateLimitPolicy


class TokenBucket:
    def __init__(self, policy: RateLimitPolicy):
        self.policy = policy
        self.capacity = float(policy.requests)
        self.tokens = float(policy.requests)
        self.rate = policy.requests / policy.per_seconds
        self.updated = time.monotonic()
        self.lock = threading.Lock()
        self.pause_until = 0.0
        self.max_rate = self.rate
        self.min_rate = min(self.rate, 0.05)

    def throttle(self) -> None:
        """Adaptive: halve the rate after a 429 (multiplicative decrease)."""
        with self.lock:
            self.rate = max(self.min_rate, self.rate / 2)

    def recover(self) -> None:
        """Adaptive: creep back towards the policy rate on success (additive increase)."""
        with self.lock:
            if self.rate < self.max_rate:
                self.rate = min(self.max_rate, self.rate + self.max_rate * 0.02)

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                if now < self.pause_until:
                    wait = self.pause_until - now
                else:
                    self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                    self.updated = now
                    if self.tokens >= 1:
                        self.tokens -= 1
                        lo, hi = self.policy.jitter
                        jitter = random.uniform(lo, hi)
                        break
                    wait = (1 - self.tokens) / self.rate
            time.sleep(wait)
        if jitter:
            time.sleep(jitter)

    def pause(self, seconds: float) -> None:
        """Honour Retry-After or a block: nobody sharing this identity sends until then."""
        with self.lock:
            self.pause_until = max(self.pause_until, time.monotonic() + seconds)


def backoff_delay(policy: RateLimitPolicy, attempt: int) -> float:
    base = min(policy.backoff_cap, policy.backoff_base**attempt)
    return base * random.uniform(0.5, 1.5)


class CircuitBreaker:
    def __init__(self, policy: RateLimitPolicy):
        self.policy = policy
        self.failures = 0
        self.opened_at: float | None = None
        self.lock = threading.Lock()

    @property
    def open(self) -> bool:
        with self.lock:
            if self.opened_at is None:
                return False
            if time.monotonic() - self.opened_at > self.policy.breaker_cooldown:
                self.opened_at = None  # half-open: let the next request probe
                self.failures = self.policy.breaker_failures - 1
                return False
            return True

    def success(self) -> None:
        with self.lock:
            self.failures = 0
            self.opened_at = None

    def failure(self) -> None:
        with self.lock:
            self.failures += 1
            if self.failures >= self.policy.breaker_failures:
                self.opened_at = time.monotonic()


_BUCKETS: dict[tuple[str, str], TokenBucket] = {}
_BREAKERS: dict[str, CircuitBreaker] = {}
_LOCK = threading.Lock()


def bucket(source: str, identity: str, policy: RateLimitPolicy) -> TokenBucket:
    with _LOCK:
        key = (source, identity)
        if key not in _BUCKETS:
            _BUCKETS[key] = TokenBucket(policy)
        return _BUCKETS[key]


def breaker(source: str, policy: RateLimitPolicy) -> CircuitBreaker:
    with _LOCK:
        if source not in _BREAKERS:
            _BREAKERS[source] = CircuitBreaker(policy)
        return _BREAKERS[source]
