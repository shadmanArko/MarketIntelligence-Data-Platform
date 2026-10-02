"""TikTok via yt-dlp (public profiles): profile video list with counts, then full metadata for recent videos
(views, likes, comments, shares, saves, duration, music, caption, hashtags, posted at).

Handles: TikTok links found on restaurant websites, plus every Instagram handle tried on TikTok (businesses
usually reuse it); a missing account is stored as a tombstone, which is itself a feature.
TikTokApi search / hashtag discovery needs an ms_token (TIKTOK_MS_TOKEN) and is not used without one.
"""

from collections.abc import Iterator
from typing import ClassVar

import yt_dlp
from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.ratelimit import bucket
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope, SourceBlocked
from mip.db import connect

MAX_VIDEOS = 200
DETAIL_VIDEOS = 40
KEEP = ("id", "title", "description", "timestamp", "upload_date", "duration", "view_count", "like_count",
        "comment_count", "repost_count", "save_count", "track", "artist", "artists", "album", "creator", "uploader",
        "uploader_id", "channel", "channel_id", "channel_follower_count", "webpage_url", "thumbnail", "tags",
        "width", "height", "format_id", "music", "is_ad", "availability")


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class Profile(_A):
    handle: str


class Video(_A):
    id: str


def _ydl(flat: bool, end: int | None = None) -> yt_dlp.YoutubeDL:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": flat, "socket_timeout": 30}
    if end:
        opts["playlistend"] = end
    return yt_dlp.YoutubeDL(opts)


@register
class TikTok:
    source: ClassVar[str] = "tiktok"
    version: ClassVar[str] = "1.0.0"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=1, per_seconds=2.5, jitter=(0.3, 1.5))
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"profile": Profile, "video": Video}

    def __init__(self, market):
        self.market = market
        self.bucket = bucket(self.source, "default", self.rate_limit)

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        with connect() as c:
            rows = c.execute("""
                select lower(h) handle, 'website' as via, max(p.payload ->> 'business_id') business_id
                from raw.observations o join raw.payloads p using (payload_sha256),
                     jsonb_array_elements_text(ops.jarr(p.payload #> '{social_links,tiktok}')) h
                where o.source = 'web_crawl' and p.payload ->> 'kind' = 'business' group by 1
                union
                select lower(h), 'instagram_handle', max(p.payload ->> 'business_id')
                from raw.observations o join raw.payloads p using (payload_sha256),
                     jsonb_array_elements_text(ops.jarr(p.payload #> '{social_links,instagram}')) h
                where o.source = 'web_crawl' and p.payload ->> 'kind' = 'business' group by 1""").fetchall()
        seen = set()
        for r in rows:
            h = r["handle"].lstrip("@")
            if h in seen or not h:
                continue
            seen.add(h)
            yield EntityRef("profile", h, {"via": r["via"], "business_id": r["business_id"]},
                            priority=20 if r["via"] == "website" else 35)
            if scope.limit and len(seen) >= scope.limit:
                return

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        self.bucket.acquire()
        if ref.entity_type == "profile":
            yield from self._profile(ref)
        else:
            yield from self._video(ref)

    def _profile(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        url = f"https://www.tiktok.com/@{ref.natural_key}"
        try:
            with _ydl(True, MAX_VIDEOS) as y:
                info = y.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "429" in msg or "blocked" in msg.lower():
                raise SourceBlocked(f"tiktok: {msg[:200]}") from e
            yield RawRecord("profile", ref.natural_key, {"handle": ref.natural_key, "exists": False,
                                                         "error": msg[:500], **ref.params}, {"url": url}, 404)
            return
        entries = info.pop("entries", None) or []
        videos = [{k: v for k, v in e.items() if k in KEEP} for e in entries]
        yield RawRecord("profile", ref.natural_key, {"handle": ref.natural_key, "exists": True, **ref.params,
                                                     **{k: v for k, v in info.items() if k in KEEP or k in (
                                                         "uploader", "channel_id", "description")},
                                                     "videos": videos}, {"url": url}, 200)
        for v in videos[:DETAIL_VIDEOS]:
            if v.get("id"):
                yield EntityRef("video", str(v["id"]), {"handle": ref.natural_key}, priority=50)

    def _video(self, ref: EntityRef) -> Iterator[RawRecord]:
        url = f"https://www.tiktok.com/@{ref.params['handle']}/video/{ref.natural_key}"
        try:
            with _ydl(False) as y:
                info = y.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            yield RawRecord("video", ref.natural_key, {"id": ref.natural_key, "error": str(e)[:500]}, {"url": url},
                            404)
            return
        yield RawRecord("video", ref.natural_key, {k: v for k, v in info.items() if k in KEEP} | {
            "handle": ref.params["handle"], "formats_count": len(info.get("formats") or [])}, {"url": url}, 200)

    def healthcheck(self) -> HealthStatus:
        try:
            with _ydl(True, 1) as y:
                info = y.extract_info("https://www.tiktok.com/@tiktok", download=False)
            return HealthStatus(bool(info.get("entries")), "public profile listing works")
        except Exception as e:
            return HealthStatus(False, str(e)[:200])
