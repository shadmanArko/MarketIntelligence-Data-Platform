"""Wolt: public consumer API. Discovery is coordinate-based, so the city is swept on an H3 grid.

Per grid point the venue list is split losslessly:
  * `coverage`      — the response envelope + every venue's location-dependent fields at that point
                      (delivers, online, estimate, delivery price, distance, sortables, promotions)
  * `venue_listing` — each venue item with those fields moved out, so it is content-addressed once
                      instead of 1,351 near-identical copies.
Follow-up work per venue: `venue_static` (legal entity, opening times, ratings), `venue_dynamic`
(order minimum, surcharges, discounts at the venue's own location) and `menu` (full assortment).
"""

from collections.abc import Iterator
from copy import deepcopy
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.http import HttpClient
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope
from mip.geo.grid import cell_center, h3_cells

API = "https://consumer-api.wolt.com"
LIST_URL = f"{API}/v1/pages/restaurants"
STATIC_URL = f"{API}/order-xp/web/v1/pages/venue/slug/{{slug}}/static/"
DYNAMIC_URL = f"{API}/order-xp/web/v1/venue/slug/{{slug}}/dynamic/"
MENU_URL = f"{API}/consumer-api/consumer-assortment/v1/venues/slug/{{slug}}/assortment"
CATEGORY_URL = f"{API}/consumer-api/consumer-assortment/v1/venues/slug/{{slug}}/assortment/categories/slug/{{cat}}"

# location-dependent fields on a venue item (moved into the coverage record)
VARIANT_VENUE_KEYS = ("delivers", "online", "estimate", "estimate_box", "estimate_range", "delivery_highlight",
                      "delivery_price_highlight", "delivery_within_time_range", "promotions",
                      "promotions_for_telemetry", "badges", "badges_v2", "show_wolt_plus", "show_zero_markup")
VARIANT_ITEM_KEYS = ("sorting", "filtering", "telemetry_object_id", "telemetry_venue_badges", "track_id")


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class Coverage(_A):
    lat: float
    lon: float
    cell: str
    venues: list[dict]


class _VenueCore(_A):
    id: str
    name: str
    slug: str
    location: list[float]


class VenueListing(_A):
    venue: _VenueCore


class _StaticVenue(_A):
    id: str
    name: str


class VenueStatic(_A):
    venue: _StaticVenue


class VenueDynamic(_A):
    venue: dict


class Menu(_A):
    categories: list[dict]
    items: list[dict]


def split_item(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(stable venue item, location-dependent fields) — together they are the original item."""
    stable = deepcopy(item)
    variant: dict[str, Any] = {}
    for k in VARIANT_ITEM_KEYS:
        if k in stable:
            variant[k] = stable.pop(k)
    v = stable.get("venue", {})
    vv: dict[str, Any] = {}
    for k in VARIANT_VENUE_KEYS:
        if k in v:
            vv[k] = v.pop(k)
    variant["venue"] = vv
    return stable, variant


@register
class Wolt:
    source: ClassVar[str] = "wolt"
    version: ClassVar[str] = "1.0.1"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=4, per_seconds=1.0, jitter=(0.05, 0.3))
    contracts: ClassVar[dict[str, type[BaseModel]]] = {
        "coverage": Coverage,
        "venue_listing": VenueListing,
        "venue_static": VenueStatic,
        "venue_dynamic": VenueDynamic,
        "menu": Menu,
    }

    def __init__(self, market):
        self.market = market
        self.cfg = market.source(self.source)
        self.http = HttpClient(self.source, self.rate_limit, headers={
            "Accept": "application/json", "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "platform": "Web", "app-language": "de", "client-version": "1.16.0",
        })
        # the per-venue dynamic endpoint is rate-limited much harder than listings and menus
        self.http.add_lane("dynamic", RateLimitPolicy(requests=1, per_seconds=1.5, jitter=(0.1, 0.5)))
        # the city-wide listing is the heaviest call and throttles at ~0.3/s; keep it from slowing menus
        self.http.add_lane("list", RateLimitPolicy(requests=1, per_seconds=2.0, jitter=(0.1, 0.6)))

    # ------------------------------------------------------------------ discover
    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        cells = h3_cells(scope.market, scope.market.geography.h3_resolution)
        for cell in cells[: scope.limit] if scope.limit else cells:
            lat, lon = cell_center(cell)
            yield EntityRef("coverage", cell, {"lat": lat, "lon": lon}, priority=10)

    # ------------------------------------------------------------------ fetch
    def fetch(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        match ref.entity_type:
            case "coverage":
                yield from self._grid_point(ref)
            case "venue_static":
                yield from self._simple(ref, STATIC_URL.format(slug=ref.natural_key))
            case "venue_dynamic":
                p = ref.params
                yield from self._simple(ref, DYNAMIC_URL.format(slug=ref.natural_key),
                                        {"lat": p.get("lat"), "lon": p.get("lon")}, lane="dynamic")
            case "menu":
                yield from self._menu(ref)
            case _:
                raise ValueError(f"wolt: unknown entity type {ref.entity_type}")

    def _grid_point(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        lat, lon = ref.params["lat"], ref.params["lon"]
        params = {"lat": lat, "lon": lon}
        r = self.http.get(LIST_URL, params=params, lane="list")
        meta = {"url": LIST_URL, "params": params, "cell": ref.natural_key}
        body = r.json()
        sections = body.pop("sections", [])
        venues_variant: list[dict] = []
        other_sections: list[dict] = []
        seen: set[str] = set()
        for sec in sections:
            items = sec.get("items", [])
            venue_items = [i for i in items if isinstance(i.get("venue"), dict) and i["venue"].get("id")]
            rest = {k: v for k, v in sec.items() if k != "items"}
            rest["non_venue_items"] = [i for i in items if i not in venue_items]
            rest["venue_ids"] = [i["venue"]["id"] for i in venue_items]
            other_sections.append(rest)
            for item in venue_items:
                stable, variant = split_item(item)
                vid = item["venue"]["id"]
                variant["venue_id"] = vid
                variant["section"] = sec.get("name")
                venues_variant.append(variant)
                if vid in seen:
                    continue
                seen.add(vid)
                yield RawRecord("venue_listing", vid, stable, meta, r.status)
                slug = item["venue"].get("slug")
                vlon, vlat = (item["venue"].get("location") or [lon, lat])[:2]
                if slug:
                    yield EntityRef("venue_static", slug, {"venue_id": vid}, priority=30)
                    yield EntityRef("venue_dynamic", slug, {"venue_id": vid, "lat": vlat, "lon": vlon}, priority=40)
                    if self.cfg.opt("menus", True):
                        yield EntityRef("menu", slug, {"venue_id": vid}, priority=50)
        coverage = {"lat": lat, "lon": lon, "cell": ref.natural_key, "envelope": body,
                    "sections": other_sections, "venues": venues_variant}
        yield RawRecord("coverage", ref.natural_key, coverage, meta, r.status)

    def _simple(self, ref: EntityRef, url: str, params: dict | None = None,
                lane: str | None = None) -> Iterator[RawRecord]:
        r = self.http.get(url, params=params, lane=lane)
        meta = {"url": url, "params": params or {}, **ref.params}
        yield RawRecord(ref.entity_type, ref.natural_key, r.json() if r.status == 200 else {"_status": r.status,
                        "_body": r.text[:2000]}, meta, r.status)

    def _menu(self, ref: EntityRef) -> Iterator[RawRecord]:
        url = MENU_URL.format(slug=ref.natural_key)
        r = self.http.get(url)
        meta = {"url": url, **ref.params}
        if r.status != 200:
            yield RawRecord("menu", ref.natural_key, {"_status": r.status, "_body": r.text[:2000]}, meta, r.status)
            return
        body = r.json()
        # "partial" loading strategy (large venues / retail): items arrive per category page
        if body.get("loading_strategy") == "partial":
            pages = []
            for cat in body.get("categories", []):
                cslug = cat.get("slug")
                if not cslug:
                    continue
                cu = CATEGORY_URL.format(slug=ref.natural_key, cat=cslug)
                cr = self.http.get(cu)
                if cr.status == 200:
                    pages.append({"category_slug": cslug, "page": cr.json()})
            body["_category_pages"] = pages
            body["items"] = body.get("items") or [i for p in pages for i in p["page"].get("items", [])]
        yield RawRecord("menu", ref.natural_key, body, meta, r.status)

    def healthcheck(self) -> HealthStatus:
        lat, lon = 52.5200, 13.4050
        r = self.http.get(LIST_URL, params={"lat": lat, "lon": lon})
        n = sum(len(s.get("items", [])) for s in r.json().get("sections", []))
        return HealthStatus(r.status == 200 and n > 0, f"{n} items at Mitte", r.elapsed_ms)
