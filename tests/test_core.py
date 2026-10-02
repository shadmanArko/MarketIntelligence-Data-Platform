from mip.core.ratelimit import CircuitBreaker, TokenBucket, backoff_delay
from mip.core.raw_store import field_paths, payload_hash
from mip.core.types import RateLimitPolicy


def test_payload_hash_is_key_order_independent():
    a, _ = payload_hash({"b": 1, "a": [1, 2]})
    b, _ = payload_hash({"a": [1, 2], "b": 1})
    assert a == b and len(a) == 32


def test_field_paths_collapse_lists():
    p = field_paths({"a": {"b": 1}, "items": [{"x": 1}, {"y": 2}]})
    assert {"a", "a.b", "items", "items[].x", "items[].y"} <= p


def test_breaker_opens_after_failures():
    br = CircuitBreaker(RateLimitPolicy(breaker_failures=3, breaker_cooldown=60))
    for _ in range(3):
        br.failure()
    assert br.open
    br.success()
    assert not br.open


def test_backoff_capped():
    pol = RateLimitPolicy(backoff_base=2, backoff_cap=10)
    assert backoff_delay(pol, 20) <= 15


def test_token_bucket_does_not_block_within_capacity():
    import time

    tb = TokenBucket(RateLimitPolicy(requests=5, per_seconds=1, jitter=(0, 0)))
    t0 = time.monotonic()
    for _ in range(5):
        tb.acquire()
    assert time.monotonic() - t0 < 0.2
