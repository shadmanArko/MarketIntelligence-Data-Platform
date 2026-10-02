"""Value types shared by every connector."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from mip.config import Market


@dataclass(frozen=True)
class RateLimitPolicy:
    requests: int = 1                 # tokens per window
    per_seconds: float = 1.0          # window length
    jitter: tuple[float, float] = (0.05, 0.4)
    backoff_base: float = 2.0
    backoff_cap: float = 300.0
    breaker_failures: int = 8         # consecutive failures before the breaker opens
    breaker_cooldown: float = 600.0


@dataclass
class Scope:
    market: Market
    limit: int | None = None          # cap discovered units (dev / sampling)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntityRef:
    """One unit of work: becomes one row in ops.tasks."""

    entity_type: str
    natural_key: str
    params: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)
    priority: int = 100


@dataclass
class RawRecord:
    entity_type: str
    natural_key: str
    payload: Any
    request_meta: dict[str, Any]
    http_status: int = 200
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class HealthStatus:
    ok: bool
    detail: str = ""
    latency_ms: int | None = None


class SourceBlocked(Exception):
    """The source refused us (403/429/challenge); retry later with backoff."""


class SourceGone(Exception):
    """The entity no longer exists (404 etc.); do not retry."""
