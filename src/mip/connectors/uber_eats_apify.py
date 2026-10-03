"""Uber Eats store list via a paid Apify actor (one-time; stores only: name, cuisines, rating, price, address).

Uber Eats serves automated browsers a bot challenge, so the platform does not scrape it directly; the Apify actor
`lentic_clockss/ubereats-scraper` is the paid fallback from the plan. Coverage: the Berlin city index plus one
delivery-address feed per district (the actor caps a run at 500 stores), de-duplicated by store uuid.

Spend is capped: `budget_usd` in the market config (default 10). Before each actor run the connector adds up the
cost of the runs it already made (Apify reports `usageTotalUsd`) and refuses to start another once the cap is hit.
"""

import time
from collections.abc import Iterator
from typing import ClassVar

import httpx
from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope, SourceBlocked
from mip.db import connect
from mip.geo.areas import areas
from mip.settings import settings

API = "https://api.apify.com/v2"
ACTOR = "lentic_clockss~ubereats-scraper"


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class Store(_A):
    title: str


class ActorRun(_A):
    run_id: str
    status: str


@register
class UberEatsApify:
    source: ClassVar[str] = "uber_eats"
    version: ClassVar[str] = "1.0.0"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=1, per_seconds=2.0, jitter=(0.0, 0.2))
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"store": Store, "actor_run": ActorRun}

    def __init__(self, market):
        self.market = market
        self.cfg = market.source(self.source)
        self.token = settings().apify_token
        self.budget = float(self.cfg.opt("budget_usd", 10))
        self.max_results = int(self.cfg.opt("max_results_per_run", 500))
        self.http = httpx.Client(timeout=60, params={"token": self.token})

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        base = {"locale": "de", "vertical": "RESTAURANTS", "enrichDetails": False, "maxResults": self.max_results}
        yield EntityRef("actor_run", "city:berlin", {**base, "mode": "city", "citySlug": "berlin", "maxPages": 0},
                        priority=10)
        for a in areas(scope.market, "district"):
            name = a.get("name") or a["code"]
            yield EntityRef("actor_run", f"feed:{name}",
                            {**base, "mode": "feed", "address": f"{name}, Berlin, Deutschland"}, priority=20)

    def _spent(self) -> float:
        with connect() as c:
            row = c.execute("""
                select coalesce(sum((p.payload ->> 'usage_usd')::numeric), 0) usd
                from raw.observations o join raw.payloads p using (payload_sha256)
                where o.source = 'uber_eats' and o.entity_type = 'actor_run'""").fetchone()
        return float(row["usd"])

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord]:
        spent = self._spent()
        if spent >= self.budget:
            raise SourceBlocked(f"uber_eats: budget ${self.budget:.2f} reached (spent ${spent:.2f}); circuit breaker open")
        r = self.http.post(f"{API}/acts/{ACTOR}/runs", json=ref.params)
        r.raise_for_status()
        run = r.json()["data"]
        run_id = run["id"]
        while run["status"] in ("READY", "RUNNING"):
            time.sleep(10)
            run = self.http.get(f"{API}/actor-runs/{run_id}").json()["data"]
        items = []
        if run.get("defaultDatasetId"):
            items = self.http.get(f"{API}/datasets/{run['defaultDatasetId']}/items",
                                  params={"clean": "true", "format": "json"}).json()
        usage = run.get("usageTotalUsd") or 0
        meta = {"actor": ACTOR, "input": ref.params, "apify_run_id": run_id}
        yield RawRecord("actor_run", ref.natural_key, {
            "run_id": run_id, "status": run["status"], "usage_usd": usage, "items": len(items),
            "input": ref.params, "stats": run.get("stats"), "started_at": run.get("startedAt"),
            "finished_at": run.get("finishedAt")}, meta, 200)
        for it in items:
            if it.get("itemType", "store") != "store":
                continue
            key = it.get("storeUuid") or it.get("uuid") or it.get("url")
            if key and it.get("title"):
                yield RawRecord("store", str(key), it, meta, 200)
        if run["status"] != "SUCCEEDED":
            raise RuntimeError(f"apify run {run_id} ended {run['status']} (stored {len(items)} rows)")

    def healthcheck(self) -> HealthStatus:
        if not self.token:
            return HealthStatus(False, "set APIFY_TOKEN in .env")
        r = self.http.get(f"{API}/users/me")
        ok = r.status_code == 200
        plan = r.json().get("data", {}).get("plan", {}).get("id") if ok else None
        return HealthStatus(ok, f"apify plan={plan}; budget cap ${self.budget:.2f}; spent ${self._spent():.2f}")
