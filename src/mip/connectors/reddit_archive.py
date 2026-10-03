"""Reddit posts via the Arctic Shift archive (public, no login): every post in the configured subreddits with title,
text, flair, media type, score, comment count and created time. Arctic Shift ingests each post seconds after it
is created and re-reads it ~1-2 days later (`_meta.retrieved_2nd_on`), so score / num_comments are the values at
that second read — a consistent "36-hour performance" label.

Reddit's own no-login JSON endpoints return 403 since 2026-05 and the official API needs manual approval, so this
is the free route. One task per (subreddit, month); pages inside a month are stored as separate raw records.
Author identities are salted-hashed before they reach raw.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.http import HttpClient
from mip.core.privacy import hash_fields
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope, SourceBlocked

API = "https://arctic-shift.photon-reddit.com/api/posts/search"
UA = {"User-Agent": "mip-market-intel/0.1 (market research data platform)"}
AUTHOR_FIELDS = ("author", "author_fullname")
DROP = ("author_flair_richtext", "author_flair_template_id", "author_flair_css_class", "author_flair_text",
        "author_flair_background_color", "author_flair_text_color", "author_patreon_flair", "author_premium",
        "author_is_blocked", "awarders")
# subreddit -> first month collected. Local Berlin/Germany life, then food + community subs worldwide.
SUBREDDITS = {
    "berlin": "2019-01", "berlinsocialclub": "2019-01", "AskAGerman": "2021-01", "germany": "2021-01",
    "de": "2024-01", "Kochen": "2019-01", "berlinfood": "2019-01", "LeckerEssen": "2021-01",
    "biryani": "2019-01", "IndianFood": "2021-01", "PakistaniFood": "2019-01", "bangladesh": "2022-01",
    "pakistan": "2024-01", "desifood": "2019-01", "IndianFoodPhotos": "2021-01", "arabs": "2023-01",
    "MiddleEasternFood": "2019-01", "TurkishFood": "2019-01", "PersianFood": "2019-01", "afghanistan": "2023-01",
    "AfricanFood": "2019-01", "Nigeria": "2024-01", "vietnamesefood": "2021-01", "KoreanFood": "2023-01",
    "food": "2024-01", "FoodPorn": "2024-01", "streetfood": "2021-01", "FoodVideos": "2021-01",
    "halal": "2019-01", "ramadan": "2019-01", "islam": "2025-01",
}
MAX_PAGES = 400   # per subreddit-month safety cap (40k posts)
SPLIT_MIN_S = 6 * 3600   # windows shorter than 6 h are not split further (retry with backoff instead)


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class Page(_A):
    subreddit: str
    month: str
    posts: list[dict]


def _months(start: str, end: date) -> Iterator[str]:
    y, m = map(int, start.split("-"))
    while (y, m) <= (end.year, end.month):
        yield f"{y:04d}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _next(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


@register
class RedditArchive:
    source: ClassVar[str] = "reddit_archive"
    version: ClassVar[str] = "1.1.0"
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=1, per_seconds=1.5, jitter=(0.1, 0.6),
                                                            backoff_cap=120)
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"posts_page": Page}

    def __init__(self, market):
        self.market = market
        cfg = market.source(self.source) if self.source in market.sources else None
        self.subs = (cfg.opt("subreddits") if cfg else None) or SUBREDDITS
        self.http = HttpClient(self.source, self.rate_limit, headers=UA, impersonate=None, timeout=90,
                               max_attempts=4)

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        today = datetime.now(UTC).date()
        # a refresh re-reads only the last two months (scores mature ~2 days after posting; older months are final)
        recent = f"{today.year - (today.month <= 2):04d}-{(today.month - 3) % 12 + 1:02d}"
        for sub, start in self.subs.items():
            for month in _months(start, today):
                if scope.options.get("refresh") and month < recent:
                    continue
                # the current and previous month are re-fetched by refreshes (scores mature ~2 days later)
                yield EntityRef("posts_month", f"{sub}|{month}", {"subreddit": sub, "month": month},
                                priority=20 if month >= "2025-01" else 40)

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        sub, month = ref.params["subreddit"], ref.params["month"]
        win = ref.params.get("window")           # [after_epoch, before_epoch] after a timeout split
        if win:
            after, before = str(win[0]), str(win[1])
        else:
            after = str(int(datetime.strptime(f"{month}-01", "%Y-%m-%d").replace(tzinfo=UTC).timestamp()))
            before = str(int(datetime.strptime(f"{_next(month)}-01", "%Y-%m-%d").replace(tzinfo=UTC).timestamp()))
        tag = f"{sub}|{month}" + (f"|{win[0]}" if win else "")
        seen: set[str] = set()
        for page in range(MAX_PAGES):
            params = {"subreddit": sub, "after": after, "before": before, "sort": "asc", "limit": "100"}
            r = self.http.get(API, params=params, ok_statuses=frozenset({200}), gone_statuses=frozenset())
            body = r.json()
            if body.get("error"):
                a, b = int(after), int(before)
                if "Timeout" in body["error"] and b - a > SPLIT_MIN_S:
                    # busy subreddit: the archive cannot scan this window in time -> split the rest of it in two
                    mid = (a + b) // 2
                    for lo, hi in ((a, mid), (mid, b)):
                        yield EntityRef("posts_month", f"{sub}|{month}|{lo}-{hi}",
                                        {"subreddit": sub, "month": month, "window": [lo, hi]}, priority=15)
                    return
                raise SourceBlocked(f"arctic_shift: {body['error']}")
            posts = []
            for p in body.get("data") or []:
                if p.get("id") in seen:
                    continue
                seen.add(p.get("id"))
                posts.append(p)
                hash_fields(p, AUTHOR_FIELDS, "reddit")
                for k in DROP:
                    p.pop(k, None)
            if posts or page == 0:
                yield RawRecord("posts_page", f"{tag}|{page:03d}",
                                {"subreddit": sub, "month": month, "page": page, "posts": posts},
                                {"url": API, "params": params}, r.status)
            if len(body.get("data") or []) < 100 or not posts:
                return
            after = str(int(max(p["created_utc"] for p in posts)) - 1)   # overlap one second; `seen` dedupes

    def healthcheck(self) -> HealthStatus:
        r = self.http.get(API, params={"subreddit": "berlin", "limit": "1"})
        return HealthStatus(r.status == 200 and bool(r.json().get("data")), "arctic shift ok", r.elapsed_ms)
