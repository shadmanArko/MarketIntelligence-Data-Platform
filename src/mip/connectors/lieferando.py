"""Lieferando (Just Eat Takeaway): one discovery query per postcode, then menu CDN + reviews per restaurant.

Same backend as Thuisbezorgd, Pyszne, Takeaway.com: `country` in the market config switches it.
Like Wolt, each postcode response is split losslessly into a `coverage` record (postcode-dependent fields,
fee bands, promoted ranks, filters) and one `restaurant_listing` per restaurant.
Follow-ups: `menu_manifest` (restaurant info, colophon/legal entity, opening times, menu structure),
`menu_items`, `menu_item_details` (modifiers), `menu_dynamic` (fees, badges, rating) and `reviews`.
"""

from collections.abc import Iterator
from copy import deepcopy
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.http import HttpClient
from mip.core.privacy import hash_fields
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope
from mip.geo.areas import areas

REST = "https://rest.api.eu-central-1.production.jet-external.com"
CDN = "https://globalmenucdn.eu-central-1.production.jet-external.com"

VARIANT_KEYS = ("driveDistanceMeters", "openingTimeLocal", "deliveryOpeningTimeLocal", "deliveryEtaMinutes",
                "isOpenNowForCollection", "isOpenNowForDelivery", "isOpenNowForPreorder", "isTemporarilyOffline",
                "deliveryCost", "minimumDeliveryValue", "defaultDisplayRank", "isTemporaryBoost", "availability",
                "deals", "isPremier")


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class Coverage(_A):
    postcode: str
    restaurants: list[dict]


class _Addr(_A):
    location: dict


class RestaurantListing(_A):
    id: str
    name: str
    uniqueName: str
    address: _Addr


class Manifest(_A):
    RestaurantId: str
    RestaurantInfo: dict


class Items(_A):
    Items: list[dict]


class Reviews(_A):
    reviews: list[dict]


def split_restaurant(r: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    stable = deepcopy(r)
    variant = {k: stable.pop(k) for k in VARIANT_KEYS if k in stable}
    variant["id"] = r["id"]
    return stable, variant


@register
class Lieferando:
    source: ClassVar[str] = "lieferando"
    version: ClassVar[str] = "1.0.1"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=4, per_seconds=1.0, jitter=(0.05, 0.3))
    contracts: ClassVar[dict[str, type[BaseModel]]] = {
        "coverage": Coverage,
        "restaurant_listing": RestaurantListing,
        "menu_manifest": Manifest,
        "menu_items": Items,
        "reviews": Reviews,
    }

    def __init__(self, market):
        self.market = market
        self.cfg = market.source(self.source)
        self.country = self.cfg.opt("country", "de")
        self.max_reviews = int(self.cfg.opt("max_reviews", 300))
        self.http = HttpClient(self.source, self.rate_limit, headers={
            "Accept": "application/json", "Accept-Language": "de-DE,de;q=0.9",
            "x-country-code": self.country, "x-language-code": "de",
        })
        self.http.add_lane("cdn", RateLimitPolicy(requests=8, per_seconds=1.0, jitter=(0.02, 0.1)))

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        pcs = sorted({a["code"] for a in areas(scope.market, "postcode")})
        for pc in pcs[: scope.limit] if scope.limit else pcs:
            yield EntityRef("coverage", pc, {"postcode": pc}, priority=10)

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        p = ref.params
        match ref.entity_type:
            case "coverage":
                yield from self._postcode(ref)
            case "menu_manifest":
                yield from self._get(ref, f"{CDN}/{ref.natural_key}_{self.country}_manifest.json", lane="cdn")
            case "menu_items":
                yield from self._get(ref, f"{CDN}/{ref.natural_key}_{self.country}_items.json", lane="cdn")
            case "menu_item_details":
                yield from self._get(ref, f"{CDN}/{ref.natural_key}_{self.country}_itemDetails.json", lane="cdn")
            case "menu_dynamic":
                yield from self._get(ref, f"{REST}/restaurant/{self.country}/{ref.natural_key}/menu/dynamic",
                                     {"serviceType": "delivery"})
            case "reviews":
                yield from self._reviews(ref, p["restaurant_id"])
            case _:
                raise ValueError(ref.entity_type)

    def _postcode(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        pc = ref.natural_key
        url = f"{REST}/discovery/{self.country}/restaurants/enriched/bypostcode/{pc}"
        r = self.http.get(url)
        meta = {"url": url, "postcode": pc}
        if r.status != 200:
            yield RawRecord("coverage", pc, {"_status": r.status, "_body": r.text[:2000], "postcode": pc,
                                             "restaurants": []}, meta, r.status)
            return
        body = r.json()
        restaurants = body.pop("restaurants", [])
        variants = []
        for rest in restaurants:
            stable, variant = split_restaurant(rest)
            variants.append(variant)
            yield RawRecord("restaurant_listing", rest["id"], stable, meta, r.status)
            slug, rid = rest.get("uniqueName"), rest["id"]
            if slug:
                yield EntityRef("menu_manifest", slug, {"restaurant_id": rid}, priority=30)
                yield EntityRef("menu_items", slug, {"restaurant_id": rid}, priority=40)
                yield EntityRef("menu_item_details", slug, {"restaurant_id": rid}, priority=45)
                yield EntityRef("menu_dynamic", slug, {"restaurant_id": rid}, priority=50)
            if self.cfg.opt("reviews", True):
                yield EntityRef("reviews", rid, {"restaurant_id": rid}, priority=60)
        yield RawRecord("coverage", pc, {"postcode": pc, **body, "restaurants": variants}, meta, r.status)

    def _get(self, ref: EntityRef, url: str, params: dict | None = None, lane: str | None = None):
        r = self.http.get(url, params=params, lane=lane)
        body = r.json() if r.status == 200 and r.content else {"_status": r.status, "_body": r.text[:2000]}
        yield RawRecord(ref.entity_type, ref.natural_key, body, {"url": url, "params": params or {}, **ref.params},
                        r.status)

    def _reviews(self, ref: EntityRef, rid: str) -> Iterator[RawRecord]:
        url = f"{REST}/restaurants/{self.country}/{rid}/reviews"
        after, page, n = None, 0, 0
        while n < self.max_reviews:
            params = {"limit": 30, **({"after": after} if after else {})}  # API rejects > 30
            r = self.http.get(url, params=params)
            if r.status != 200:
                yield RawRecord("reviews", f"{rid}:{page}", {"_status": r.status, "_body": r.text[:2000],
                                                             "reviews": []}, {"url": url, "params": params}, r.status)
                return
            body = r.json()
            for rev in body.get("reviews", []):
                hash_fields(rev, ("customerName",), "lieferando")
            yield RawRecord("reviews", f"{rid}:{page}", body, {"url": url, "params": params, "restaurant_id": rid,
                                                               "page": page}, r.status)
            got = len(body.get("reviews", []))
            n += got
            after = (body.get("paging") or {}).get("cursors", {}).get("after")
            if not got or not after:
                return
            page += 1

    def healthcheck(self) -> HealthStatus:
        r = self.http.get(f"{REST}/discovery/{self.country}/restaurants/enriched/bypostcode/10117")
        n = len(r.json().get("restaurants", [])) if r.status == 200 else 0
        return HealthStatus(n > 0, f"{n} restaurants in 10117", r.elapsed_ms)
