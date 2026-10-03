"""Focused web crawler: every business website found on Google Maps / OSM / Overture / delivery listings,
plus Berlin food media and guides (config seeds). Depth-limited per site, robots.txt and crawl-delay honoured.

Stored per page (`web_page`): final URL, status, headers, the HTML (capped), and what we extract right away
so nothing needs re-crawling later: trafilatura main text + metadata, schema.org JSON-LD / microdata /
OpenGraph (extruct), outgoing links, social links and the detected online-ordering provider.
"""

import re
from collections.abc import Iterator
from typing import ClassVar
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import extruct
import trafilatura
from pydantic import BaseModel, ConfigDict

from mip.core.connector import register
from mip.core.http import HttpClient
from mip.core.types import EntityRef, HealthStatus, RateLimitPolicy, RawRecord, Scope, SourceGone
from mip.db import connect
from mip.settings import ROOT

MAX_HTML = 600_000
MAX_PAGES_PER_SITE = {"business": 25, "media": 300}  # total per site across the whole crawl
RELEVANT_PATH = re.compile(
    r"(speise|karte|menu|menü|essen|food|kontakt|contact|impressum|about|ueber|über|bestell|order|liefer|"
    r"delivery|reserv|oeffnung|öffnung|hours|restaurant|berlin|biryani|indisch|halal|imbiss|review|test|guide)",
    re.I)
SOCIAL = {
    "instagram": re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})/?(?:[?#]|$)", re.I),
    "facebook": re.compile(r"facebook\.com/([A-Za-z0-9.\-]{3,80})/?(?:[?#]|$)", re.I),
    "tiktok": re.compile(r"tiktok\.com/@([A-Za-z0-9_.]{2,30})", re.I),
    "youtube": re.compile(r"youtube\.com/(?:@|c/|channel/)([A-Za-z0-9_\-]{2,80})", re.I),
    "x": re.compile(r"(?:twitter|x)\.com/([A-Za-z0-9_]{2,15})/?(?:[?#]|$)", re.I),
    "whatsapp": re.compile(r"(?:wa\.me|api\.whatsapp\.com/send\?phone=)(\+?\d{6,15})", re.I),
}
SOCIAL_STOP = {"sharer", "share", "intent", "p", "reel", "explore", "tr", "plugins", "dialog", "home", "watch"}
ORDERING = {
    "lieferando": r"lieferando\.de", "wolt": r"wolt\.com", "uber_eats": r"ubereats\.com",
    "foodora": r"foodora\.de", "deliveroo": r"deliveroo\.", "gloriafood": r"gloriafood|fbgcdn\.com",
    "orderbird": r"orderbird", "simpledelivery": r"simpledelivery", "foodbooking": r"foodbooking\.com",
    "lieferservice_website": r"(online[- ]?bestell|jetzt bestellen|order online|warenkorb|add to cart)",
    "quandoo": r"quandoo\.", "opentable": r"opentable\.", "thefork": r"thefork\.", "resmio": r"resmio",
    "tischreservieren": r"tischreservieren\.com", "dish_order": r"dish\.co", "sumup": r"sumup\.", "wix_restaurants": r"wixrestaurants|wix-restaurants",
    "whatsapp_order": r"wa\.me/|api\.whatsapp\.com",
}


HOST_POLICY = RateLimitPolicy(requests=1, per_seconds=1.5, jitter=(0.1, 0.6))


class _A(BaseModel):
    model_config = ConfigDict(extra="allow")


class WebPage(_A):
    url: str
    final_url: str
    status: int


def canonical(url: str) -> str:
    p = urlsplit(url.strip())
    scheme = p.scheme.lower() or "https"
    host = (p.hostname or "").lower()
    path = re.sub(r"/{2,}", "/", p.path or "/")
    query = "&".join(q for q in p.query.split("&") if q and not re.match(r"(utm_|fbclid|gclid|ref=)", q))
    return urlunsplit((scheme, host, path, query, ""))


def site_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def extract(html: str, url: str) -> dict:
    out: dict = {}
    try:
        meta = trafilatura.extract_metadata(html, default_url=url)
        out["meta"] = ({k: v for k, v in meta.as_dict().items()
                        if v is None or isinstance(v, (str, int, float, bool, list))} if meta else None)
    except Exception:
        out["meta"] = None
    try:
        out["main_text"] = trafilatura.extract(html, url=url, include_comments=False, include_tables=True,
                                               favor_recall=True)
    except Exception:
        out["main_text"] = None
    try:
        out["structured"] = extruct.extract(html, base_url=url, syntaxes=["json-ld", "microdata", "opengraph"],
                                            uniform=True, errors="ignore")
    except Exception:
        out["structured"] = None
    links = set(re.findall(r'href=["\']([^"\'#\s>]+)', html, re.I))
    absolute = sorted({urljoin(url, h) for h in links if not h.startswith(("mailto:", "tel:", "javascript:"))})
    out["outgoing_links"] = absolute[:800]
    socials: dict[str, list[str]] = {}
    for name, rx in SOCIAL.items():
        handles = {m.group(1).rstrip("/") for h in absolute for m in [rx.search(h)] if m}
        handles = {h for h in handles if h.lower() not in SOCIAL_STOP}
        if handles:
            socials[name] = sorted(handles)
    out["social_links"] = socials
    low = html.lower()
    out["ordering_providers"] = sorted(k for k, rx in ORDERING.items() if re.search(rx, low))
    out["emails"] = sorted(set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", html)))[:20]
    out["phones"] = sorted(set(re.findall(r"(?:\+49|0049|\b0)\s?\(?\d{2,5}\)?[\s/-]?\d{3,}[\s-]?\d{0,6}", html)))[:20]
    out["lang_attr"] = (re.search(r'<html[^>]*\slang=["\']?([a-zA-Z-]+)', html) or [None, None])[1]
    return out


@register
class WebCrawl:
    source: ClassVar[str] = "web_crawl"
    version: ClassVar[str] = "1.0.1"
    # global ceiling; politeness is per host (HOST_POLICY): one request every ~1.5 s to any single site
    rate_limit: ClassVar[RateLimitPolicy] = RateLimitPolicy(requests=25, per_seconds=1.0, jitter=(0.0, 0.05),
                                                            backoff_cap=30.0, breaker_failures=10_000)  # many independent sites
    contracts: ClassVar[dict[str, type[BaseModel]]] = {"web_page": WebPage}

    def __init__(self, market):
        self.market = market
        self.cfg = market.source(self.source)
        self.max_depth = int(self.cfg.opt("max_depth", 2))
        self.http = HttpClient(self.source, self.rate_limit, max_attempts=2, timeout=25, headers={
            "Accept": "text/html,application/xhtml+xml", "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"})
        self._robots: dict[str, RobotFileParser | None] = {}
        self.respect_robots = bool(self.cfg.opt("respect_robots", True))

    def discover(self, scope: Scope) -> Iterator[EntityRef]:
        seeds_file = ROOT / "config" / str(self.cfg.opt("seeds", "seeds/berlin_food_media.txt"))
        media = [ln.strip() for ln in seeds_file.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
        for u in media:
            yield EntityRef("web_page", canonical(u), {"url": u, "depth": 0, "kind": "media", "site": site_of(u)},
                            priority=20)
        with connect() as c:
            rows = c.execute("""
                SELECT DISTINCT ON (website_domain) business_id::text AS business_id, website
                FROM core.business WHERE website IS NOT NULL AND in_market
                  AND website !~* '(facebook|instagram|google|wolt|lieferando|ubereats|linktr\\.ee|tiktok)\\.'
                ORDER BY website_domain, listing_count DESC""").fetchall()
        for i, r in enumerate(rows):
            if scope.limit and i >= scope.limit:
                break
            yield EntityRef("web_page", canonical(r["website"]),
                            {"url": r["website"], "depth": 0, "kind": "business", "site": site_of(r["website"]),
                             "business_id": r["business_id"]}, priority=30)

    def _lane(self, url: str) -> str:
        host = site_of(url)
        if host not in self.http.extra_buckets:
            self.http.add_lane(host, HOST_POLICY)
        return host

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        site = site_of(url)
        if site not in self._robots:
            rp = RobotFileParser()
            try:
                r = self.http.get(f"{urlsplit(url).scheme}://{urlsplit(url).netloc}/robots.txt",
                                  ok_statuses=frozenset({200, 404, 403, 401}), gone_statuses=frozenset(),
                                  lane=self._lane(url))
                rp.parse(r.text.splitlines() if r.status == 200 else [])
                self._robots[site] = rp
            except Exception:
                self._robots[site] = None
        rp = self._robots[site]
        return rp is None or rp.can_fetch("*", url)

    def fetch(self, ref: EntityRef) -> Iterator[RawRecord | EntityRef]:
        p = ref.params
        url = p["url"]
        if not self._allowed(url):
            yield RawRecord("web_page", ref.natural_key, {"url": url, "final_url": url, "status": 999,
                                                          "blocked_by_robots": True, **p}, {"url": url}, 299)
            return
        try:
            r = self.http.get(url, ok_statuses=frozenset(range(200, 300)), gone_statuses=frozenset({404, 410}),
                              lane=self._lane(url))
        except SourceGone:
            yield RawRecord("web_page", ref.natural_key, {"url": url, "final_url": url, "status": 404, **p},
                            {"url": url}, 404)
            return
        except Exception as e:  # dead domain, TLS failure, timeout: a real signal about the business
            if "circuit breaker" in str(e):
                raise
            yield RawRecord("web_page", ref.natural_key, {"url": url, "final_url": url, "status": 0,
                                                          "error": f"{type(e).__name__}: {str(e)[:300]}", **p},
                            {"url": url}, 599)
            return
        ctype = r.headers.get("content-type", "")
        payload = {"url": url, "final_url": r.url, "status": r.status, "content_type": ctype,
                   "headers": {k: v for k, v in r.headers.items() if k.lower() in (
                       "content-type", "last-modified", "server", "x-powered-by", "content-language")},
                   **{k: v for k, v in p.items() if k != "url"}}
        if "html" not in ctype.lower():
            yield RawRecord("web_page", ref.natural_key, payload, {"url": url}, r.status)
            return
        html = r.text
        payload["html"] = html[:MAX_HTML]
        payload["html_truncated"] = len(html) > MAX_HTML
        payload.update(extract(html, r.url))
        yield RawRecord("web_page", ref.natural_key, payload, {"url": url}, r.status)
        # follow same-site links that look relevant, up to max depth and a per-site page budget for the whole crawl
        if p["depth"] >= self.max_depth:
            return
        site = site_of(r.url)
        budget = MAX_PAGES_PER_SITE.get(p.get("kind", "business"), 25)
        with connect() as c:
            used = c.execute("SELECT count(*) n FROM ops.tasks WHERE source='web_crawl' AND params->>'site' = %s",
                             (p.get("site") or site,)).fetchone()["n"]
        room = budget - used
        for link in payload.get("outgoing_links", []):
            if room <= 0:
                break
            if site_of(link) != site or not link.startswith("http"):
                continue
            if re.search(r"\.(pdf|jpe?g|png|gif|webp|svg|zip|mp4|css|js)(\?|$)", link, re.I) and not (
                    link.lower().endswith(".pdf") and re.search(r"(speise|karte|menu)", link, re.I)):
                continue
            if p["kind"] == "business" or RELEVANT_PATH.search(urlsplit(link).path):
                room -= 1
                yield EntityRef("web_page", canonical(link), {**p, "url": link, "depth": p["depth"] + 1},
                                priority=40 + p["depth"])

    def healthcheck(self) -> HealthStatus:
        r = self.http.get("https://www.berlin.de/", ok_statuses=frozenset(range(200, 400)))
        return HealthStatus(r.status < 400, f"berlin.de {r.status}", r.elapsed_ms)
