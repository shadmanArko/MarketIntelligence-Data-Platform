"""HTTP client for every connector: browser TLS fingerprint, rate limits, retries, dev cache."""

import hashlib
import random
import time
from dataclasses import dataclass
from typing import Any

import orjson
import structlog
from curl_cffi import requests as creq

from mip.core.ratelimit import backoff_delay, breaker, bucket
from mip.core.types import RateLimitPolicy, SourceBlocked, SourceGone
from mip.settings import settings

log = structlog.get_logger()

IMPERSONATE = ["chrome131", "chrome133a", "chrome136", "safari184", "edge101"]
RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504, 520, 522, 524}


@dataclass
class Response:
    status: int
    url: str
    headers: dict[str, str]
    content: bytes
    elapsed_ms: int
    from_cache: bool = False

    def json(self) -> Any:
        return orjson.loads(self.content)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class HttpClient:
    """One client per connector instance. Identity = the account/IP the bucket is keyed by."""

    def __init__(
        self,
        source: str,
        policy: RateLimitPolicy,
        identity: str = "default",
        impersonate: str | None = None,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        max_attempts: int = 5,
        timeout: float = 30.0,
    ):
        self.source = source
        self.policy = policy
        self.identity = identity
        self.bucket = bucket(source, identity, policy)
        self.extra_buckets: dict[str, object] = {}
        self.breaker = breaker(source, policy)
        self.impersonate = impersonate or random.choice(IMPERSONATE)
        self.session = creq.Session(impersonate=self.impersonate, timeout=timeout, proxy=proxy)
        if headers:
            self.session.headers.update(headers)
        self.max_attempts = max_attempts
        self.stats = {"requests": 0, "2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "bytes": 0, "cache_hits": 0}
        self.cache_dir = settings().data_dir / "cache" / source if settings().mip_dev_cache else None

    def _cache_path(self, method: str, url: str, params, body):
        if not self.cache_dir:
            return None
        key = orjson.dumps([method, url, params, body], option=orjson.OPT_SORT_KEYS)
        h = hashlib.sha256(key).hexdigest()
        return self.cache_dir / h[:2] / f"{h}.bin"

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json: Any = None,
        data: Any = None,
        headers: dict | None = None,
        ok_statuses: frozenset[int] = frozenset({200}),
        gone_statuses: frozenset[int] = frozenset({404, 410}),
        lane: str | None = None,
    ) -> Response:
        """`lane` gives an endpoint its own token bucket (see `add_lane`)."""
        bkt = self.extra_buckets[lane] if lane else self.bucket
        cpath = self._cache_path(method, url, params, json or data)
        if cpath and cpath.exists():
            blob = orjson.loads(cpath.read_bytes())
            self.stats["cache_hits"] += 1
            return Response(blob["status"], blob["url"], blob["headers"], bytes.fromhex(blob["content"]), 0, True)

        last_err: Exception | None = None
        for attempt in range(self.max_attempts):
            if self.breaker.open:
                raise SourceBlocked(f"{self.source}: circuit breaker open")
            if lane:
                self.bucket.acquire()  # source-wide ceiling first, then the lane's own pace
            bkt.acquire()
            t0 = time.monotonic()
            try:
                r = self.session.request(method, url, params=params, json=json, data=data, headers=headers)
            except Exception as e:  # network errors, TLS resets
                last_err = e
                self.breaker.failure()
                delay = backoff_delay(self.policy, attempt)
                log.warning("http.error", source=self.source, url=url, error=str(e)[:200], retry_in=round(delay, 1))
                time.sleep(delay)
                continue
            elapsed = int((time.monotonic() - t0) * 1000)
            self.stats["requests"] += 1
            self.stats[f"{r.status_code // 100}xx"] = self.stats.get(f"{r.status_code // 100}xx", 0) + 1
            self.stats["bytes"] += len(r.content)
            resp = Response(r.status_code, str(r.url), dict(r.headers), r.content, elapsed)

            if r.status_code in ok_statuses:
                self.breaker.success()
                bkt.recover()
                if cpath:
                    cpath.parent.mkdir(parents=True, exist_ok=True)
                    cpath.write_bytes(
                        orjson.dumps(
                            {"status": resp.status, "url": resp.url, "headers": resp.headers,
                             "content": resp.content.hex()}
                        )
                    )
                return resp
            if r.status_code in gone_statuses:
                self.breaker.success()
                raise SourceGone(f"{self.source}: {r.status_code} {url}")
            if r.status_code in RETRY_STATUSES or r.status_code == 403:
                if r.status_code == 429:
                    bkt.throttle()  # rate limit: slow down, the source is fine
                else:
                    self.breaker.failure()
                retry_after = r.headers.get("retry-after")
                delay = (
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else backoff_delay(self.policy, attempt + (2 if r.status_code in (403, 429) else 0))
                )
                if r.status_code in (403, 429):
                    bkt.pause(delay)
                    # rotate TLS fingerprint on blocks
                    self.impersonate = random.choice(IMPERSONATE)
                    hdrs = dict(self.session.headers)
                    self.session = creq.Session(impersonate=self.impersonate, timeout=self.session.timeout)
                    self.session.headers.update(hdrs)
                log.warning("http.retry", source=self.source, status=r.status_code, url=url, retry_in=round(delay, 1))
                last_err = SourceBlocked(f"{self.source}: HTTP {r.status_code} {url}")
                time.sleep(delay)
                continue
            # other 4xx: return so the caller can decide (stored in raw with its status)
            return resp
        raise last_err or SourceBlocked(f"{self.source}: exhausted retries for {url}")

    def add_lane(self, lane: str, policy: RateLimitPolicy) -> None:
        self.extra_buckets[lane] = bucket(self.source, f"{self.identity}:{lane}", policy)

    def get(self, url: str, **kw) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> Response:
        return self.request("POST", url, **kw)
