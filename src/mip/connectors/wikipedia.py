"""Wikipedia page views (daily, since 2015-07) for dishes, cuisines and occasions: an open, free demand-interest
time series (Google Trends substitute). Seeds are English article titles; their language versions (de, bn, ur,
ar, tr, hi) are resolved through the MediaWiki langlinks API so titles are always exact."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import ClassVar
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.http import HttpClient
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope

UA = {"User-Agent": "mip-market-intel/0.1 (market research data platform; contact: repository owner)"}
PV = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/all-access/user/{title}/daily/{start}/{end}"
LANGS = ("de", "bn", "ur", "ar", "tr", "hi")
SEEDS = ["Biryani", "Bangladeshi cuisine", "Haleem", "Mandi (food)", "Kabsa", "Tehari", "Pilaf", "Korma",
         "Butter chicken", "Nihari", "Kebab", "Doner kebab", "Falafel", "Shawarma", "Pizza", "Sushi", "Ramen",
         "Indian cuisine", "Pakistani cuisine", "Afghan cuisine", "Arab cuisine", "Halal", "Ramadan",
         "Eid al-Fitr", "Eid al-Adha", "Pohela Boishakh", "Lassi", "Samosa", "Food delivery", "Lieferando", "Wolt"]


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class Pageviews(_A):
    project: str
    title: str
    items: list[dict]


@register
class Wikipedia:
    source: ClassVar[str] = "wikipedia"
    version: ClassVar[str] = "1.0.0"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=5, per_seconds=1.0, jitter=(0.05, 0.2))
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"pageviews": Pageviews}

    def __init__(self, market):
        self.market = market
        self.seeds = market.source(self.source).opt("seeds", SEEDS) if self.source in market.sources else SEEDS
        self.http = HttpClient(self.source, self.rate_limit, headers=UA, impersonate=None)

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        for seed in self.seeds:
            yield EntityRef("pageviews", f"en.wikipedia|{seed}", {"project": "en.wikipedia", "title": seed,
                                                                   "seed": seed, "lang": "en"}, priority=10)
            r = self.http.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query", "titles": seed, "prop": "langlinks", "lllimit": "500", "redirects": "1",
                "format": "json"})
            pages = r.json().get("query", {}).get("pages", {})
            for page in pages.values():
                for ll in page.get("langlinks", []):
                    if ll["lang"] in LANGS:
                        title = ll["*"]
                        yield EntityRef("pageviews", f"{ll['lang']}.wikipedia|{title}",
                                        {"project": f"{ll['lang']}.wikipedia", "title": title, "seed": seed,
                                         "lang": ll["lang"]}, priority=20)

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord]:
        p = ref.params
        end = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y%m%d00")
        url = PV.format(project=f"{p['project']}.org", title=quote(p["title"].replace(" ", "_"), safe=""),
                        start="2015070100", end=end)
        r = self.http.get(url, ok_statuses=frozenset({200, 404}), gone_statuses=frozenset())
        items = r.json().get("items", []) if r.status == 200 else []
        yield RawRecord("pageviews", ref.natural_key, {**p, "items": items, "through": end}, {"url": url}, r.status)

    def healthcheck(self) -> HealthStatus:
        r = self.http.get(PV.format(project="en.wikipedia.org", title="Biryani", start="2024010100", end="2024010200"))
        return HealthStatus(r.status == 200, "pageviews API ok", r.elapsed_ms)
