"""YouTube Data API v3 (free key): videos, Shorts and channels about Berlin food, biryani and every community's
meat-and-rice dishes and occasions — title, description, tags, language, duration, publish time, views, likes,
comments, plus the comment language mix on the most relevant videos (commenter identities hashed).

Quota (2026): search.list has its own bucket of ~100 calls/day; every other call costs 1 unit of 10,000/day.
So searches are rationed (`search_budget_per_day`) and everything else is fetched by cheap id batches:
  search (query x order)  -> videos (<=50 ids, 1 unit) + channels (<=50 ids, 1 unit)
  channels                -> uploads (playlistItems, 50/page) -> videos
  videos (tier-1 queries) -> comments (commentThreads, top 100)
A `--refresh` run re-reads video statistics, which gives metrics snapshots (rule 2).
"""

import os
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import httpx
import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.http import HttpClient
from mip.core.privacy import pseudonym
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope, SourceBlocked
from mip.db import connect
from mip.settings import ROOT

API = "https://www.googleapis.com/youtube/v3"
VIDEO_PARTS = "snippet,statistics,contentDetails,topicDetails,status,localizations,recordingDetails"
CHANNEL_PARTS = "snippet,statistics,contentDetails,brandingSettings,topicDetails"
UPLOAD_PAGES = 4          # latest 200 uploads per channel
COMMENTS_MIN = 20         # only read comments of videos that have a conversation


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class SearchPage(_A):
    query: str
    items: list[dict]


class Videos(_A):
    items: list[dict]


class Channels(_A):
    items: list[dict]


class Uploads(_A):
    items: list[dict]


class Comments(_A):
    video_id: str
    items: list[dict]


def _env(name: str) -> str:
    return os.environ.get(name) or dotenv_values(ROOT / ".env").get(name) or ""


def _key() -> str:
    return _env("YOUTUBE_API_KEY")


_TOKEN: dict = {}
_TOKEN_LOCK = threading.Lock()


def _oauth_token() -> str:
    """Access token from the OAuth refresh token (YOUTUBE_CLIENT_ID / _SECRET / _REFRESH_TOKEN), cached until expiry.
    The connector only ever reads; the token's write scopes are never used."""
    with _TOKEN_LOCK:
        if _TOKEN.get("exp", 0) > time.time() + 60:
            return _TOKEN["access_token"]
        r = httpx.post("https://oauth2.googleapis.com/token", timeout=30, data={
            "client_id": _env("YOUTUBE_CLIENT_ID"), "client_secret": _env("YOUTUBE_CLIENT_SECRET"),
            "refresh_token": _env("YOUTUBE_REFRESH_TOKEN"), "grant_type": "refresh_token"})
        if r.status_code != 200:
            raise SourceBlocked(f"youtube oauth refresh failed: HTTP {r.status_code}")
        body = r.json()
        _TOKEN.update(access_token=body["access_token"], exp=time.time() + int(body.get("expires_in", 3600)))
        return _TOKEN["access_token"]


def _auth() -> tuple[dict, dict]:
    """(extra params, extra headers): API key if set, else OAuth bearer token."""
    if _key():
        return {"key": _key()}, {}
    if _env("YOUTUBE_REFRESH_TOKEN"):
        return {}, {"Authorization": f"Bearer {_oauth_token()}"}
    raise SourceBlocked("set YOUTUBE_API_KEY or YOUTUBE_CLIENT_ID/_SECRET/_REFRESH_TOKEN in .env")


def queries() -> list[dict]:
    """Configured queries + every community dish (native name and transliteration) in its home region."""
    cfg = yaml.safe_load((ROOT / "config" / "keywords" / "social_content.yaml").read_text())["queries"]
    com = yaml.safe_load((ROOT / "config" / "taxonomies" / "communities.yaml").read_text())["communities"]
    out, seen = [], set()
    for q in cfg:
        out.append({**q, "source": "config"})
        seen.add(q["q"].lower())
    for cid, c in com.items():
        region = (c.get("countries") or ["DE"])[0]
        lang = (c.get("languages") or ["en"])[0].split("-")[0]
        for d in c.get("dishes", []):
            for q in {d["native"], d["translit"]}:
                if q.lower() not in seen:
                    seen.add(q.lower())
                    out.append({"q": q, "region": region if len(region) == 2 else "DE", "lang": lang, "tier": 3,
                                "source": f"dish:{cid}:{d['id']}"})
    return out


@register
class YouTube:
    source: ClassVar[str] = "youtube"
    version: ClassVar[str] = "1.1.0"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=5, per_seconds=1.0, jitter=(0.05, 0.3),
                                                            breaker_failures=4)
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"search": SearchPage, "videos": Videos, "channels": Channels,
                                                       "uploads": Uploads, "comments": Comments}

    def __init__(self, market):
        self.market = market
        cfg = market.source(self.source) if self.source in market.sources else None
        self.search_budget = int(cfg.opt("search_budget_per_day", 90)) if cfg else 90
        self.http = HttpClient(self.source, self.rate_limit, impersonate=None, timeout=60, max_attempts=3)

    # ------------------------------------------------------------------ discovery
    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        week = datetime.now(UTC).strftime("%G-W%V")
        if scope.options.get("refresh"):
            # weekly statistics snapshot of every known video (1 unit per 50) + this week's recent searches only
            with connect() as c:
                ids = [r["id"] for r in c.execute(
                    "select distinct x.value ->> 'id' id from raw.observations o join raw.payloads p using"
                    " (payload_sha256), jsonb_array_elements(p.payload -> 'items') x where o.source = 'youtube'"
                    " and o.entity_type = 'videos' order by 1").fetchall() if r["id"]]
            for i in range(0, len(ids), 50):
                batch = ids[i:i + 50]
                yield EntityRef("videos", ",".join(batch), {"ids": batch, "tier": 3}, priority=25)
        for q in queries():
            if scope.options.get("refresh") and q["tier"] > 2:
                continue
            base = {"q": q["q"], "region": q["region"], "lang": q["lang"], "tier": q["tier"], "origin": q["source"]}
            # all-time most viewed: once; recent uploads: once per ISO week (the trend signal)
            if not scope.options.get("refresh"):
                yield EntityRef("search", f"{q['q']}|{q['region']}|viewCount", {**base, "order": "viewCount"},
                                priority=10 * q["tier"])
            if q["tier"] <= 2:
                yield EntityRef("search", f"{q['q']}|{q['region']}|recent|{week}", {**base, "order": "date",
                                "published_after_days": 30}, priority=10 * q["tier"] + 5)
        if _env("YOUTUBE_CHANNEL_ID"):   # Dhaka Kacchi's own channel: every upload + weekly stats
            yield EntityRef("channels", f"own:{_env('YOUTUBE_CHANNEL_ID')}",
                            {"lookup": {"id": _env("YOUTUBE_CHANNEL_ID")}, "origin": "restaurant_website"}, priority=5)
        with connect() as c:   # channels linked from Berlin restaurant websites
            rows = c.execute("select distinct handle from core.social_link_candidate where platform='youtube'"
                             " and handle is not null").fetchall()
        for r in rows:
            h = r["handle"]
            param = {"id": h} if h.startswith("UC") and len(h) == 24 else {"forHandle": "@" + h.lstrip("@")}
            yield EntityRef("channels", f"site:{h}", {"lookup": param, "origin": "restaurant_website"}, priority=15)

    # ------------------------------------------------------------------ fetch
    def _get(self, path: str, params: dict) -> dict:
        auth_params, auth_headers = _auth()
        r = self.http.get(f"{API}/{path}", params={**params, **auth_params}, headers=auth_headers or None,
                          ok_statuses=frozenset({200, 403, 404}), gone_statuses=frozenset())
        body = r.json()
        if r.status == 403:
            reason = ((body.get("error") or {}).get("errors") or [{}])[0].get("reason", "")
            if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
                raise SourceBlocked(f"youtube quota: {reason}")
            if reason in ("commentsDisabled", "forbidden"):
                return {"items": [], "disabled": reason}
            raise SourceBlocked(f"youtube 403: {reason}")
        return body

    def _searches_today(self) -> int:
        with connect() as c:
            return c.execute("select count(*) n from raw.observations where source='youtube' and entity_type='search'"
                             " and fetched_at >= date_trunc('day', now() at time zone 'America/Los_Angeles')"
                             " at time zone 'America/Los_Angeles'").fetchone()["n"]   # quota resets at Pacific midnight

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        p = ref.params
        if ref.entity_type == "search":
            if self._searches_today() >= self.search_budget:
                raise SourceBlocked("youtube search budget for today used; continue tomorrow")
            params = {"part": "snippet", "q": p["q"], "type": "video", "maxResults": 50, "order": p["order"],
                      "regionCode": p["region"], "relevanceLanguage": p["lang"], "safeSearch": "none"}
            if p.get("published_after_days"):
                params["publishedAfter"] = (datetime.now(UTC) - timedelta(days=p["published_after_days"])
                                            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            body = self._get("search", params)
            items = body.get("items", [])
            yield RawRecord("search", ref.natural_key, {**p, "query": p["q"], "items": items,
                                                       "pageInfo": body.get("pageInfo")}, {"params": params}, 200)
            vids = [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]
            chans = sorted({i["snippet"]["channelId"] for i in items if i.get("snippet", {}).get("channelId")})
            if vids:
                yield EntityRef("videos", ",".join(sorted(vids)), {"ids": vids, "tier": p["tier"]}, priority=30)
            if chans:
                yield EntityRef("channels", ",".join(chans), {"lookup": {"id": ",".join(chans)}, "origin": "search",
                                                              "tier": p["tier"]}, priority=40)
        elif ref.entity_type == "videos":
            body = self._get("videos", {"part": VIDEO_PARTS, "id": ",".join(p["ids"]), "maxResults": 50})
            items = body.get("items", [])
            yield RawRecord("videos", ref.natural_key, {"items": items, "tier": p.get("tier")}, {"ids": p["ids"]}, 200)
            if p.get("tier", 3) <= 1:
                for v in items:
                    if int((v.get("statistics") or {}).get("commentCount") or 0) >= COMMENTS_MIN:
                        yield EntityRef("comments", v["id"], {"video_id": v["id"]}, priority=60)
        elif ref.entity_type == "channels":
            body = self._get("channels", {"part": CHANNEL_PARTS, **p["lookup"], "maxResults": 50})
            items = body.get("items", [])
            yield RawRecord("channels", ref.natural_key, {"items": items, "origin": p.get("origin")},
                            {"lookup": p["lookup"]}, 200)
            for ch in items:
                country = (ch.get("snippet") or {}).get("country")
                uploads = ((ch.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
                if uploads and (country == "DE" or p.get("origin") == "restaurant_website" or p.get("tier") == 1):
                    yield EntityRef("uploads", f"{uploads}|0", {"playlist": uploads, "page": 0, "channel": ch["id"]},
                                    priority=50)
        elif ref.entity_type == "uploads":
            params = {"part": "contentDetails,snippet", "playlistId": p["playlist"], "maxResults": 50}
            if p.get("token"):
                params["pageToken"] = p["token"]
            body = self._get("playlistItems", params)
            items = body.get("items", [])
            yield RawRecord("uploads", ref.natural_key, {"items": items, "channel": p["channel"]}, {"params": params},
                            200)
            vids = [i["contentDetails"]["videoId"] for i in items if i.get("contentDetails", {}).get("videoId")]
            if vids:
                yield EntityRef("videos", ",".join(sorted(vids)), {"ids": vids, "tier": 2}, priority=55)
            if body.get("nextPageToken") and p["page"] + 1 < UPLOAD_PAGES:
                yield EntityRef("uploads", f"{p['playlist']}|{p['page'] + 1}", {
                    **p, "page": p["page"] + 1, "token": body["nextPageToken"]}, priority=55)
        elif ref.entity_type == "comments":
            body = self._get("commentThreads", {"part": "snippet", "videoId": p["video_id"], "maxResults": 100,
                                                "order": "relevance", "textFormat": "plainText"})
            items = []
            for t in body.get("items", []):
                s = ((t.get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
                items.append({"id": t.get("id"), "text": s.get("textOriginal"), "likes": s.get("likeCount"),
                              "published_at": s.get("publishedAt"), "replies": t["snippet"].get("totalReplyCount"),
                              "author": pseudonym(s.get("authorChannelId", {}).get("value"), "youtube")})
            yield RawRecord("comments", p["video_id"], {"video_id": p["video_id"], "items": items,
                                                        "disabled": body.get("disabled")}, {}, 200)

    def healthcheck(self) -> HealthStatus:
        try:
            auth_params, auth_headers = _auth()
        except SourceBlocked as e:
            return HealthStatus(False, str(e))
        r = self.http.get(f"{API}/videos", params={"part": "id", "id": "dQw4w9WgXcQ", **auth_params},
                          headers=auth_headers or None, ok_statuses=frozenset({200, 400, 401, 403}))
        return HealthStatus(r.status == 200, f"HTTP {r.status} ({'api key' if _key() else 'oauth'})", r.elapsed_ms)
