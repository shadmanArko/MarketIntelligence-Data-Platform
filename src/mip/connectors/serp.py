"""Search rankings for the keywords Berliners type (config/keywords/*.txt, {district} expanded).

Providers:
  * `local`   — Google Maps local results for the keyword, centred on each district and on the whole city
                (the map pack ranking), via the same template replay as the google_maps connector. Free.
  * `organic` — official search APIs with a free tier, used when a key is in .env:
                Google Programmable Search JSON API (GOOGLE_CSE_KEY + GOOGLE_CSE_CX, 100 queries/day) or
                Brave Search API (BRAVE_API_KEY). Scraping search engines' HTML is not attempted: they answer
                with bot challenges.
Paid provider `dataforseo` (Google organic + map pack + ads per device) plugs in behind the same entity types
once a budget exists; keyword volumes likewise.
"""

from collections.abc import Iterator
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from mip.connectors.google_maps import CONSENT, SEARCH, build_pb, load_template, parse_response, safe, strip_tokens
from mip.core.connector import register
from mip.core.http import HttpClient
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope
from mip.geo.areas import areas
from mip.settings import settings

GOOGLE_CSE = "https://www.googleapis.com/customsearch/v1"
BRAVE = "https://api.search.brave.com/res/v1/web/search"


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class LocalSerp(_A):
    keyword: str
    area: str
    results: list[dict]


class OrganicSerp(_A):
    keyword: str
    results: list[dict]


def expand_keywords(market) -> list[str]:
    districts = sorted({a["name"] for a in areas(market, "district") if a.get("name")})
    out = []
    for kw in market.keywords_list():
        if "{district}" in kw:
            out += [kw.replace("{district}", d.lower()) for d in districts]
        else:
            out.append(kw)
    return sorted(set(out))


@register
class Serp:
    source: ClassVar[str] = "serp"
    version: ClassVar[str] = "1.0.0"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=1, per_seconds=4.0, jitter=(0.5, 2.0))
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"local_serp": LocalSerp, "organic_serp": OrganicSerp}

    def __init__(self, market):
        self.market = market
        self.http = HttpClient(self.source, self.rate_limit, headers={"Accept-Language": "de-DE,de;q=0.9"})
        self.http.session.cookies.set("SOCS", CONSENT, domain=".google.com")
        self.http.add_lane("api", RateLimitPolicy(requests=1, per_seconds=1.1, jitter=(0.0, 0.2)))
        st = settings()
        self.cse = (st.google_cse_key, st.google_cse_cx) if st.google_cse_key and st.google_cse_cx else None
        self.brave = st.brave_api_key or None

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        kws = expand_keywords(scope.market)
        centres = [("berlin", 52.5200, 13.4050, 14000)] + [
            (a["name"].lower(), a["lat"], a["lon"], 5000) for a in areas(scope.market, "district") if a.get("name")]
        for kw in kws[: scope.limit] if scope.limit else kws:
            for area, lat, lon, vp in centres:
                yield EntityRef("local_serp", f"{kw}|{area}", {"keyword": kw, "area": area, "lat": lat, "lon": lon,
                                                               "viewport_m": vp}, priority=20)
            if self.cse or self.brave:
                yield EntityRef("organic_serp", kw, {"keyword": kw}, priority=30)

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord]:
        if ref.entity_type == "local_serp":
            yield from self._local(ref)
        else:
            yield from self._organic(ref)

    def _local(self, ref: EntityRef) -> Iterator[RawRecord]:
        p = ref.params
        tpl = load_template()
        results = []
        for offset in (0, 20):  # top 40 is what people see and scroll
            pb = build_pb(tpl["pb"], p["lat"], p["lon"], p["viewport_m"], offset)
            r = self.http.get(SEARCH, params={"tbm": "map", "authuser": "0", "hl": "de", "gl": "de",
                                              "q": p["keyword"], "pb": pb})
            entries = (parse_response(r.text)[64] or []) if r.status == 200 else []
            for rank, e in enumerate(entries):
                entry = safe(e, 1)
                if not isinstance(entry, list):
                    continue
                stable, _ = strip_tokens(entry)
                results.append({"rank": offset + rank + 1, "fid": safe(entry, 10), "name": safe(entry, 11),
                                "place_id": safe(entry, 78), "lat": safe(entry, 9, 2), "lon": safe(entry, 9, 3),
                                "rating": safe(entry, 4, 7), "reviews": safe(entry, 4, 8),
                                "categories": safe(entry, 13), "website": safe(entry, 7, 0),
                                "is_ad": bool(safe(e, 0))})
            if len(entries) < 20:
                break
        yield RawRecord("local_serp", ref.natural_key, {**p, "provider": "google_maps_local", "results": results},
                        {"url": SEARCH, "q": p["keyword"]}, 200)

    def _organic(self, ref: EntityRef) -> Iterator[RawRecord]:
        kw = ref.params["keyword"]
        if self.cse:
            key, cx = self.cse
            results, raw_pages = [], []
            for start in (1, 11):
                r = self.http.get(GOOGLE_CSE, params={"key": key, "cx": cx, "q": kw, "gl": "de", "hl": "de",
                                                      "num": 10, "start": start}, lane="api")
                body = r.json() if r.status == 200 else {"_status": r.status}
                raw_pages.append(body)
                for i, it in enumerate(body.get("items", []), start):
                    results.append({"rank": i, "url": it.get("link"), "title": it.get("title"),
                                    "snippet": it.get("snippet"), "is_ad": False})
            yield RawRecord("organic_serp", kw, {"keyword": kw, "provider": "google_cse", "results": results,
                                                 "pages": raw_pages}, {"url": GOOGLE_CSE, "q": kw}, 200)
        elif self.brave:
            r = self.http.get(BRAVE, params={"q": kw, "country": "de", "search_lang": "de", "count": 20}, lane="api",
                              headers={"X-Subscription-Token": self.brave, "Accept": "application/json"})
            body = r.json() if r.status == 200 else {"_status": r.status}
            results = [{"rank": i, "url": it.get("url"), "title": it.get("title"), "snippet": it.get("description"),
                        "is_ad": False} for i, it in enumerate(body.get("web", {}).get("results", []), 1)]
            yield RawRecord("organic_serp", kw, {"keyword": kw, "provider": "brave", "results": results,
                                                 "response": body}, {"url": BRAVE, "q": kw}, r.status)

    def healthcheck(self) -> HealthStatus:
        return HealthStatus(True, "uses google_maps template + duckduckgo html")
