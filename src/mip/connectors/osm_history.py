"""OpenStreetMap history via the ohsome API (HeiGIT): when food places appeared, changed and disappeared on the
map since 2010, per Berlin district.

* `element_history` — every version of every food POI in the district (centroid + tags + validFrom / validTo):
                      opening / closing proxies and name or cuisine changes per place.
* `monthly_counts`  — monthly counts per district x cuisine: supply growth curves per neighbourhood.
"""

import json
from collections.abc import Iterator
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.http import HttpClient
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope
from mip.geo.areas import areas

API = "https://api.ohsome.org/v1"
START, END = "2010-01-01", "2026-07-01"   # ohsome data currently ends 2026-07-27
FOOD = "amenity in (restaurant, fast_food, cafe, bar, pub, biergarten, ice_cream, food_court)"
CUISINES = ("indian,pakistani,bangladeshi,nepalese,afghan,arab,lebanese,syrian,persian,turkish,kebab,pizza,italian,"
            "burger,sushi,vietnamese,thai,chinese,asian,german,regional,greek,mexican,coffee_shop,bakery,chicken")


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class History(_A):
    district: str
    features: list[dict]


class Counts(_A):
    district: str
    groupByResult: list[dict]


@register
class OsmHistory:
    source: ClassVar[str] = "osm_history"
    version: ClassVar[str] = "1.0.0"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=1, per_seconds=2.0, jitter=(0.1, 0.5))
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"element_history": History, "monthly_counts": Counts}

    def __init__(self, market):
        self.market = market
        self.http = HttpClient(self.source, self.rate_limit, impersonate=None, timeout=600, max_attempts=3,
                               headers={"User-Agent": "mip-market-intel/0.1 (research)"})

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        for a in areas(scope.market, "district"):
            name = a.get("name") or a["code"]
            for et in ("element_history", "monthly_counts"):
                yield EntityRef(et, name, {"district": name, "code": a["code"]}, priority=20)

    def _bpolys(self, district: str) -> str:
        geom = next(a["geometry"] for a in areas(self.market, "district") if (a.get("name") or a["code"]) == district)
        return json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"id": district}, "geometry": geom}]})

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord]:
        d = ref.params["district"]
        if ref.entity_type == "element_history":
            url = f"{API}/elementsFullHistory/centroid"
            data = {"bpolys": self._bpolys(d), "time": f"{START},{END}", "filter": FOOD,
                    "properties": "tags,metadata"}
            r = self.http.post(url, data=data)
            body = r.json()
            yield RawRecord("element_history", d, {"district": d, "features": body.get("features", []),
                                                   "attribution": body.get("attribution")},
                            {"url": url, "time": data["time"], "filter": FOOD}, r.status)
        else:
            url = f"{API}/elements/count/groupBy/tag"
            data = {"bpolys": self._bpolys(d), "time": f"{START}/{END}/P1M", "filter": FOOD,
                    "groupByKey": "cuisine", "groupByValues": CUISINES}
            r = self.http.post(url, data=data)
            body = r.json()
            yield RawRecord("monthly_counts", d, {"district": d, "groupByResult": body.get("groupByResult", []),
                                                  "attribution": body.get("attribution")},
                            {"url": url, "time": data["time"], "filter": FOOD}, r.status)

    def healthcheck(self) -> HealthStatus:
        r = self.http.get(f"{API}/metadata")
        return HealthStatus(r.status == 200, str(r.json().get("extractRegion", {}).get("temporalExtent")), r.elapsed_ms)
