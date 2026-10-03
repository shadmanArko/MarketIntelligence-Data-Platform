"""Tenant first-party data from the Dhaka Kacchi AI Harness warehouse (read-only): the business's own Instagram,
Facebook and Threads posts with every metrics snapshot (reach, likes, comments, shares, saves, clicks), and —
when the reader role allows it — orders. This is the ground truth the market data is calibrated against.

Connection: `DK_WAREHOUSE_DSN` in .env. Locally that is the harness's dev database; for live nightly data, open an
SSH tunnel to the VPS (see docs/credentials-guide.md) and point the DSN at `warehouse_reader` through it.
Every query runs in a READ ONLY transaction; the connector cannot write to the source.
"""

import os
from collections.abc import Iterator
from typing import ClassVar

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope
from mip.settings import ROOT

POSTS_SQL = """
select p.id::text, p.platform, p.external_id, p.posted_at, p.permalink, p.content_type, p.caption,
       p.created_at, p.updated_at,
       coalesce(json_agg(json_build_object(
         'captured_at', s.captured_at, 'impressions', s.impressions, 'reach', s.reach, 'likes', s.likes,
         'comments', s.comments, 'shares', s.shares, 'saves', s.saves, 'clicks', s.clicks)
         order by s.captured_at) filter (where s.id is not null), '[]') as snapshots
from social_post p left join social_metrics_snapshot s on s.social_post_id = p.id
group by p.id
"""
ORDERS_SQL = """
select o.*, coalesce((select json_agg(row_to_json(l)) from order_line l where l.order_id = o.id), '[]') as lines
from orders o
"""


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class OwnPost(_A):
    platform: str
    external_id: str


def _dsn() -> str:
    from dotenv import dotenv_values

    return os.environ.get("DK_WAREHOUSE_DSN") or dotenv_values(ROOT / ".env").get("DK_WAREHOUSE_DSN") or ""


@register
class FirstParty:
    source: ClassVar[str] = "first_party"
    version: ClassVar[str] = "1.0.0"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=50, per_seconds=1.0, jitter=(0, 0))
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"own_post": OwnPost}

    def __init__(self, market):
        self.market = market
        self.tenant = "dhaka-kacchi"

    def _read(self, sql: str) -> list[dict]:
        with psycopg.connect(_dsn(), row_factory=dict_row, autocommit=False) as c:
            c.execute("SET TRANSACTION READ ONLY")
            rows = c.execute(sql).fetchall()
            c.rollback()
        return rows

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        yield EntityRef("own_posts", self.tenant, {"tenant_id": self.tenant}, priority=10)
        yield EntityRef("own_orders", self.tenant, {"tenant_id": self.tenant}, priority=20)

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord]:
        meta = {"tenant_id": self.tenant, "source_db": _dsn().split("@")[-1]}
        if ref.entity_type == "own_posts":
            for r in self._read(POSTS_SQL):
                yield RawRecord("own_post", f"{r['platform']}:{r['external_id']}",
                                {**{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()},
                                 "tenant_id": self.tenant}, meta, 200)
        else:
            try:
                rows = self._read(ORDERS_SQL)
            except psycopg.errors.InsufficientPrivilege as e:
                yield RawRecord("own_orders_access", self.tenant, {"error": str(e)[:300]}, meta, 403)
                return
            for r in rows:
                yield RawRecord("own_order", str(r["id"]), {
                    **{k: (v.isoformat() if hasattr(v, "isoformat") else str(v) if not isinstance(
                        v, (int, float, str, list, dict, type(None), bool)) else v) for k, v in r.items()},
                    "tenant_id": self.tenant}, meta, 200)

    def healthcheck(self) -> HealthStatus:
        if not _dsn():
            return HealthStatus(False, "set DK_WAREHOUSE_DSN in .env")
        n = self._read("select count(*) n, max(posted_at) last from social_post")[0]
        return HealthStatus(True, f"{n['n']} own posts, latest {n['last']} @ {_dsn().split('@')[-1]}")
