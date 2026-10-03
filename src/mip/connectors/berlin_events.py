"""Berlin public events from berlin.de open JSON feeds: street and folk festivals and Christmas markets (dates,
district, address, organiser, description). Footfall and food-stall occasions per district; refreshed weekly so
newly announced events appear as new observations."""

from collections.abc import Iterator
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.http import HttpClient
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope

BASE = "https://www.berlin.de/sen/web/service/maerkte-feste/{feed}/index.php/index/all.json?q="
FEEDS = {"street_festivals": "strassen-volksfeste", "christmas_markets": "weihnachtsmaerkte",
         "weekly_markets": "wochen-troedelmaerkte"}
UA = {"User-Agent": "mip-market-intel/0.1 (market research data platform)"}


class Feed(BaseModel):
    model_config = ConfigDict(extra="allow")
    feed: str
    index: list[dict]


@register
class BerlinEvents:
    source: ClassVar[str] = "berlin_events"
    version: ClassVar[str] = "1.0.0"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=1, per_seconds=2.0)
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"feed": Feed}

    def __init__(self, market):
        self.market = market
        self.http = HttpClient(self.source, self.rate_limit, headers=UA, impersonate=None, timeout=60)

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        for name in FEEDS:
            yield EntityRef("feed", name, {"feed": name}, priority=20)

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord]:
        url = BASE.format(feed=FEEDS[ref.natural_key])
        r = self.http.get(url, ok_statuses=frozenset({200, 404}), gone_statuses=frozenset())
        body = r.json() if r.status == 200 else {}
        yield RawRecord("feed", ref.natural_key, {"feed": ref.natural_key, "index": body.get("index", []),
                                                  "results": body.get("results")}, {"url": url}, r.status)

    def healthcheck(self) -> HealthStatus:
        r = self.http.get(BASE.format(feed=FEEDS["street_festivals"]))
        return HealthStatus(r.status == 200, f"{len(r.json().get('index', []))} festivals", r.elapsed_ms)
