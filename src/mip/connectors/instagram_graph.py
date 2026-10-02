"""Instagram Graph API (official): Business Discovery for competitor business/creator accounts and their
media, plus Hashtag Search (top + recent media). Uses the tenant's own Instagram business account token.

Handles to look up come from the web crawl (social links on restaurant sites), OSM / Overture social tags and
`discovery.search_terms`. Limits: ~200 calls / hour / account; 30 unique hashtags per rolling 7 days.
Business accounts are stored in full (they are businesses); commenters never appear in these endpoints.
"""

from collections.abc import Iterator
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.http import HttpClient
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope
from mip.db import connect
from mip.settings import settings

GRAPH = "https://graph.facebook.com/v23.0"
MEDIA_FIELDS = ("id,caption,comments_count,like_count,media_type,media_product_type,media_url,permalink,"
                "thumbnail_url,timestamp,username,children{id,media_type,media_url,thumbnail_url}")
ACCOUNT_FIELDS = ("id,ig_id,username,name,biography,website,followers_count,follows_count,media_count,"
                  "profile_picture_url")
HASHTAG_MEDIA_FIELDS = "id,caption,comments_count,like_count,media_type,media_product_type,permalink,timestamp"
MAX_MEDIA_PAGES = 10   # 25 per page -> 250 most recent posts per account


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class Account(_A):
    username: str


class MediaPage(_A):
    username: str
    media: list[dict]


class HashtagMedia(_A):
    hashtag: str
    edge: str
    data: list[dict]


@register
class InstagramGraph:
    source: ClassVar[str] = "instagram_graph"
    version: ClassVar[str] = "1.0.0"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=190, per_seconds=3600, jitter=(0.5, 2.0))
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"account": Account, "media_page": MediaPage,
                                                       "hashtag_media": HashtagMedia}

    def __init__(self, market):
        self.market = market
        st = settings()
        self.token, self.ig_user = st.meta_access_token, st.meta_ig_user_id
        self.http = HttpClient(self.source, self.rate_limit, identity=self.ig_user or "none")

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        with connect() as c:
            handles = c.execute("""
                with crawl as (
                  select lower(h) as handle, (p.payload ->> 'business_id') as business_id
                  from raw.observations o join raw.payloads p using (payload_sha256),
                       jsonb_array_elements_text(ops.jarr(p.payload #> '{social_links,instagram}')) h
                  where o.source = 'web_crawl' and p.payload ->> 'kind' = 'business'),
                osm as (
                  select lower(regexp_replace(instagram, '^.*instagram\\.com/|/.*$|@', '', 'g')) as handle, null::text
                  from staging.stg_osm__poi where instagram is not null)
                select handle, max(business_id) as business_id from (select * from crawl union all select * from osm) x
                where handle ~ '^[a-z0-9_.]{2,30}$' group by 1""").fetchall()
        for i, h in enumerate(handles):
            if scope.limit and i >= scope.limit:
                break
            yield EntityRef("account", h["handle"], {"business_id": h["business_id"]}, priority=20)
        for tag in scope.market.discovery.hashtags:
            for edge in ("top_media", "recent_media"):
                yield EntityRef("hashtag_media", f"{tag}|{edge}", {"hashtag": tag, "edge": edge}, priority=40)

    def _get(self, path: str, params: dict):
        return self.http.get(f"{GRAPH}/{path}", params={**params, "access_token": self.token},
                             ok_statuses=frozenset({200, 400}), gone_statuses=frozenset())

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        if ref.entity_type == "account":
            yield from self._account(ref)
        elif ref.entity_type == "media_page":
            yield from self._media_page(ref)
        else:
            yield from self._hashtag(ref)

    def _account(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        u = ref.natural_key
        fields = f"business_discovery.username({u}){{{ACCOUNT_FIELDS},media.limit(25){{{MEDIA_FIELDS}}}}}"
        r = self._get(self.ig_user, {"fields": fields})
        body = r.json()
        bd = body.get("business_discovery")
        meta = {"endpoint": "business_discovery", "username": u, **ref.params}
        if not bd:  # personal account, unknown handle, or error: keep the answer, it is a signal
            yield RawRecord("account", u, {"username": u, "error": body.get("error"), "not_business": True}, meta,
                            r.status)
            return
        media = bd.pop("media", {}) or {}
        yield RawRecord("account", u, bd, meta, 200)
        yield RawRecord("media_page", f"{u}|0", {"username": u, "page": 0, "media": media.get("data", []),
                                                 "paging": media.get("paging")}, meta, 200)
        after = (media.get("paging") or {}).get("cursors", {}).get("after")
        if after:
            yield EntityRef("media_page", f"{u}|1", {"username": u, "page": 1, "after": after}, priority=30)

    def _media_page(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        p = ref.params
        fields = (f"business_discovery.username({p['username']}){{media.after({p['after']}).limit(25)"
                  f"{{{MEDIA_FIELDS}}}}}")
        r = self._get(self.ig_user, {"fields": fields})
        media = (r.json().get("business_discovery") or {}).get("media", {}) or {}
        yield RawRecord("media_page", ref.natural_key, {"username": p["username"], "page": p["page"],
                                                        "media": media.get("data", []), "paging": media.get("paging")},
                        {"endpoint": "business_discovery.media", **p}, r.status)
        after = (media.get("paging") or {}).get("cursors", {}).get("after")
        if after and p["page"] + 1 < MAX_MEDIA_PAGES:
            yield EntityRef("media_page", f"{p['username']}|{p['page'] + 1}",
                            {"username": p["username"], "page": p["page"] + 1, "after": after}, priority=30)

    def _hashtag(self, ref: EntityRef) -> Iterator[RawRecord]:
        p = ref.params
        hid = self._get("ig_hashtag_search", {"user_id": self.ig_user, "q": p["hashtag"]}).json().get("data", [{}])
        hid = hid[0].get("id") if hid else None
        if not hid:
            yield RawRecord("hashtag_media", ref.natural_key, {"hashtag": p["hashtag"], "edge": p["edge"], "data": [],
                                                               "error": "hashtag not found"}, p, 200)
            return
        data = []
        after = None
        for _ in range(4):  # 50 per page
            params = {"user_id": self.ig_user, "fields": HASHTAG_MEDIA_FIELDS, "limit": 50}
            if after:
                params["after"] = after
            body = self._get(f"{hid}/{p['edge']}", params).json()
            data += body.get("data", [])
            after = (body.get("paging") or {}).get("cursors", {}).get("after")
            if not after:
                break
        yield RawRecord("hashtag_media", ref.natural_key, {"hashtag": p["hashtag"], "hashtag_id": hid,
                                                           "edge": p["edge"], "data": data}, p, 200)

    def healthcheck(self) -> HealthStatus:
        if not (self.token and self.ig_user):
            return HealthStatus(False, "set META_ACCESS_TOKEN and META_IG_USER_ID in .env (Instagram business "
                                       "account linked to a Facebook Page + Meta app with instagram_basic)")
        r = self._get(self.ig_user, {"fields": "username,followers_count"})
        body = r.json()
        return HealthStatus("username" in body, str(body)[:200], r.elapsed_ms)
