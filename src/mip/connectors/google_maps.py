"""Google Maps, free route: the Maps web search endpoint, swept over the H3 grid for several food terms.

A real headless browser opens Google Maps once to capture a valid request template (`pb` parameter);
after that every grid cell × term × page is a plain curl_cffi request. If Google changes the format, the
healthcheck fails and `refresh_template()` captures a fresh one.

Each page is split losslessly like the delivery apps:
  * `search_page` — query, cell, offset, result order and every per-request token (ei / ved / search ids)
  * `place`       — the place entry with those tokens replaced by "~", content-addressed per place
Paging stops when a page brings no new place inside the cell's neighbourhood or after `max_pages`.
Follow-up per place: `reviews` (newest first, reviewer identity hashed) when enabled.
"""

import asyncio
import json
import re
import threading
from collections.abc import Iterator
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit

import h3
from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.http import HttpClient
from mip.core.privacy import pseudonym
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope, SourceBlocked
from mip.geo.grid import cell_center, h3_cells
from mip.settings import settings

SEARCH = "https://www.google.com/search"
CONSENT = "CAESEwgDEgk0ODE3Nzk3MjQaAmRlIAEaBgiA_LyaBg"  # consent cookie: "reject all"
DEFAULT_TERMS = ["restaurant", "imbiss", "café", "bar", "bäckerei", "lieferservice", "essen"]
VIEWPORT_BY_RES = {7: 3200, 8: 1300, 9: 500}
TOKEN_RE = re.compile(r"^(?:[02]ahUKE|0CA|CgpyZXN0|,AOvVaw)")
_TEMPLATE_LOCK = threading.Lock()
_SEEN_LOCK = threading.Lock()
_SEEN: dict[str, frozenset] = {}   # per process (= per run): fid -> non-null field paths already stored


def nonnull_paths(obj: Any, path: str = "") -> set[str]:
    if obj is None or obj == "~":
        return set()
    if isinstance(obj, list):
        out: set[str] = set()
        for i, v in enumerate(obj):
            out |= nonnull_paths(v, f"{path}/{i}")
        return out
    return {path}


def should_store(fid: str, stable: list) -> bool:
    """First sighting in this run, or a later search that adds fields we have not stored yet."""
    paths = frozenset(nonnull_paths(stable))
    with _SEEN_LOCK:
        known = _SEEN.get(fid)
        if known is not None and paths <= known:
            return False
        _SEEN[fid] = paths | (known or frozenset())
        return True


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class SearchPage(_A):
    query: str
    cell: str
    offset: int
    place_ids: list[str]


class Place(_A):
    fid: str
    entry: list


class Reviews(_A):
    fid: str
    page: int


def template_path():
    return settings().data_dir / "cache" / "google_maps_template.json"


def parse_response(text: str) -> Any:
    if text.startswith("{"):
        obj, _ = json.JSONDecoder().raw_decode(text)
        text = obj["d"]
    return json.loads(text[text.index("\n") + 1 :])


def strip_tokens(obj: Any, path: str = "", out: dict | None = None) -> tuple[Any, dict]:
    """Replace per-request tokens with '~' and return them by path, so the place body is stable."""
    out = {} if out is None else out
    if isinstance(obj, str) and TOKEN_RE.match(obj):
        out[path] = obj
        return "~", out
    if isinstance(obj, list):
        return [strip_tokens(v, f"{path}/{i}", out)[0] for i, v in enumerate(obj)], out
    return obj, out


def safe(entry: list, *idx, default=None):
    cur: Any = entry
    for i in idx:
        if not isinstance(cur, list) or i >= len(cur) or cur[i] is None:
            return default
        cur = cur[i]
    return cur


async def _capture_template() -> dict:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(locale="de-DE", viewport={"width": 1280, "height": 900})
        await ctx.add_cookies([{"name": "SOCS", "value": CONSENT, "domain": ".google.com", "path": "/"}])
        page = await ctx.new_page()
        urls: list[str] = []
        page.on("request", lambda req: urls.append(req.url) if "tbm=map" in req.url and "!8i" in req.url else None)
        await page.goto("https://www.google.com/maps/search/restaurant/@52.5200,13.4050,16z?hl=de",
                        wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        feed = page.locator('div[role="feed"]')
        for _ in range(4):
            if await feed.count():
                await feed.first.evaluate("e => e.scrollBy(0, 5000)")
            await page.wait_for_timeout(1500)
            if urls:
                break
        await b.close()
    if not urls:
        raise SourceBlocked("google_maps: could not capture a search template")
    qs = parse_qs(urlsplit(urls[0]).query)
    return {"pb": qs["pb"][0]}


def refresh_template() -> dict:
    with _TEMPLATE_LOCK:
        tpl = asyncio.run(_capture_template())
        template_path().parent.mkdir(parents=True, exist_ok=True)
        template_path().write_text(json.dumps(tpl))
        return tpl


def load_template() -> dict:
    p = template_path()
    if p.exists():
        return json.loads(p.read_text())
    return refresh_template()


def build_pb(tpl: str, lat: float, lon: float, viewport_m: float, offset: int) -> str:
    pb = re.sub(r"!1d[\d.]+!2d[\d.]+!3d[\d.]+", f"!1d{viewport_m}!2d{lon}!3d{lat}", tpl, count=1)
    return re.sub(r"!8i\d+", f"!8i{offset}", pb, count=1)


@register
class GoogleMaps:
    source: ClassVar[str] = "google_maps"
    version: ClassVar[str] = "1.1.0"
    # Google throttles an IP after a few thousand fast searches; slow and steady finishes the city
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=1, per_seconds=3.0, jitter=(0.5, 2.0),
                                                            breaker_failures=12)
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"search_page": SearchPage, "place": Place,
                                                       "reviews": Reviews}

    def __init__(self, market):
        self.market = market
        self.cfg = market.source(self.source)
        self.terms = self.cfg.opt("terms", DEFAULT_TERMS)
        self.max_pages = int(self.cfg.opt("max_pages", 10))
        self.start_res = int(self.cfg.opt("start_res", 7))
        self.max_res = int(self.cfg.opt("max_res", 9))
        self.http = HttpClient(self.source, self.rate_limit, headers={"Accept-Language": "de-DE,de;q=0.9"})
        self.http.session.cookies.set("SOCS", CONSENT, domain=".google.com")
        self.tpl = load_template()

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        cells = h3_cells(scope.market, self.start_res, buffer_rings=1)
        for n, cell in enumerate(cells, 1):
            for term in self.terms:
                yield self._ref(cell, term, 0)
            if scope.limit and n >= scope.limit:
                return

    def _ref(self, cell: str, term: str, offset: int) -> EntityRef:
        lat, lon = cell_center(cell)
        res = h3.get_resolution(cell)
        return EntityRef("search_page", f"{cell}|{term}|{offset}",
                         {"cell": cell, "term": term, "lat": lat, "lon": lon, "offset": offset,
                          "viewport_m": VIEWPORT_BY_RES.get(res, 1300)}, priority=10 + res)

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        if ref.entity_type == "search_page":
            yield from self._search(ref)
        else:
            raise ValueError(ref.entity_type)

    def _search(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        p = ref.params
        pb = build_pb(self.tpl["pb"], p["lat"], p["lon"], p["viewport_m"], p["offset"])
        params = {"tbm": "map", "authuser": "0", "hl": "de", "gl": "de", "q": p["term"], "pb": pb}
        r = self.http.get(SEARCH, params=params)
        meta = {"url": SEARCH, "params": {k: v for k, v in params.items() if k != "pb"}, "cell": p["cell"]}
        try:
            body = parse_response(r.text)
        except Exception as e:
            raise SourceBlocked(f"google_maps: unparseable response ({e}); template may be stale") from e
        entries = (body[64] if len(body) > 64 else None) or []
        res = h3.get_resolution(p["cell"])
        neighbourhood = set(h3.grid_disk(p["cell"], 1))
        place_ids, variants, in_cell = [], [], 0
        for rank, e in enumerate(entries):
            entry = safe(e, 1)
            if not isinstance(entry, list):
                continue
            fid = safe(entry, 10)
            if not fid:
                continue
            stable, tokens = strip_tokens(entry)
            place_ids.append(fid)
            stored = should_store(fid, stable)
            variants.append({"fid": fid, "rank": p["offset"] + rank, "tokens": tokens, "wrapper": e[0],
                             "stored": stored})
            if stored:
                yield RawRecord("place", fid, {"fid": fid, "entry": stable}, meta, r.status)
            lat, lon = safe(entry, 9, 2), safe(entry, 9, 3)
            if lat is not None and h3.latlng_to_cell(lat, lon, res) in neighbourhood:
                in_cell += 1
        envelope = [None if i == 64 else v for i, v in enumerate(body)]
        envelope, env_tokens = strip_tokens(envelope)
        yield RawRecord("search_page", ref.natural_key, {
            "query": p["term"], "cell": p["cell"], "offset": p["offset"], "lat": p["lat"], "lon": p["lon"],
            "viewport_m": p["viewport_m"], "place_ids": place_ids, "results": variants,
            "envelope": envelope, "envelope_tokens": env_tokens,
        }, meta, r.status)
        # next page while results keep landing in this cell; a cell still full after max_pages is subdivided
        page = p["offset"] // 20
        if len(entries) >= 20 and in_cell > 0:
            if page + 1 < self.max_pages:
                yield self._ref(p["cell"], p["term"], p["offset"] + 20)
            elif res < self.max_res:
                for child in h3.cell_to_children(p["cell"], res + 1):
                    yield self._ref(child, p["term"], 0)

    def healthcheck(self) -> HealthStatus:
        for attempt in range(2):
            pb = build_pb(self.tpl["pb"], 52.52, 13.405, 1500, 0)
            r = self.http.get(SEARCH, params={"tbm": "map", "hl": "de", "gl": "de", "q": "restaurant", "pb": pb})
            try:
                n = len(parse_response(r.text)[64] or [])
            except Exception:
                n = 0
            if n:
                return HealthStatus(True, f"{n} places at Mitte", r.elapsed_ms)
            if attempt == 0:
                self.tpl = refresh_template()
        return HealthStatus(False, "no places returned even with a fresh template")


__all__ = ["GoogleMaps", "pseudonym", "refresh_template"]
