"""Rice dishes of the world from Wikidata: QID, origin countries, meat ingredients, labels + aliases in the languages
of Berlin's communities, and the Wikipedia article titles per language. Seeds dish / keyword matching in captions
and post titles, and the Wikipedia interest connector. Curated truth stays in config/taxonomies/communities.yaml."""

import json
import time
from datetime import date

import httpx

from mip.config import Market
from mip.datasets import already_loaded, bulk_dir, console, loader, register, table_name
from mip.db import connect

SPARQL = "https://query.wikidata.org/sparql"
API = "https://www.wikidata.org/w/api.php"
UA = {"User-Agent": "mip-market-intel/0.1 (market research data platform)"}
LANGS = ("en", "de", "ar", "bn", "fa", "tr", "ur", "hi", "ps", "ku", "ru", "uk", "uz", "kk", "az", "vi", "zh", "ko",
         "ja", "th", "id", "ms", "tl", "es", "pt", "fr", "it", "pl", "el", "ro", "sr", "bg", "sq", "he", "am", "so",
         "sw", "ha", "yo", "ne", "si", "ta", "te", "ml")
QUERY = """
SELECT ?dish (GROUP_CONCAT(DISTINCT ?c; separator="|") AS ?origin)
       (GROUP_CONCAT(DISTINCT ?ing; separator="|") AS ?meat) (GROUP_CONCAT(DISTINCT ?cls; separator="|") AS ?classes)
WHERE {
  { ?dish wdt:P31|wdt:P279 ?cls . ?cls wdt:P279* wd:Q21976260 . }
  UNION { ?dish wdt:P31/wdt:P279* wd:Q746549 . ?dish (wdt:P186|wdt:P527) ?r . ?r wdt:P279* wd:Q5090 . BIND(wd:Q5090 AS ?cls) }
  OPTIONAL { ?dish (wdt:P186|wdt:P527) ?ing . ?ing wdt:P279* wd:Q10990 . }
  OPTIONAL { ?dish wdt:P495 ?c . }
} GROUP BY ?dish
"""


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


@loader("wikidata_dishes")
def load_wikidata_dishes(market: Market, version: str | None = None) -> None:
    ver = version or date.today().isoformat()
    name = "wikidata_rice_dishes"
    if already_loaded(name, ver):
        console.print("wikidata dishes already loaded")
        return
    r = httpx.get(SPARQL, params={"query": QUERY, "format": "json"}, headers=UA, timeout=300)
    r.raise_for_status()
    base = {}
    for b in r.json()["results"]["bindings"]:
        q = _qid(b["dish"]["value"])
        base[q] = {"origin": [_qid(x) for x in b.get("origin", {}).get("value", "").split("|") if x],
                   "meat": [_qid(x) for x in b.get("meat", {}).get("value", "").split("|") if x],
                   "classes": [_qid(x) for x in b.get("classes", {}).get("value", "").split("|") if x]}
    qids = list(base)
    extra = sorted({q for v in base.values() for q in v["origin"] + v["meat"]})
    ents: dict = {}
    for chunk in [qids[i:i + 50] for i in range(0, len(qids), 50)] + [extra[i:i + 50] for i in range(0, len(extra), 50)]:
        for attempt in range(6):
            time.sleep(1.5)
            resp = httpx.get(API, params={"action": "wbgetentities", "ids": "|".join(chunk), "format": "json",
                                          "props": "labels|aliases|sitelinks|claims", "languages": "|".join(LANGS),
                                          "maxlag": "5"}, headers=UA, timeout=120)
            if resp.status_code == 200:
                break
            time.sleep(min(120, int(resp.headers.get("retry-after", 0) or 0) or 10 * 2 ** attempt))
        resp.raise_for_status()
        ents.update(resp.json().get("entities", {}))
    (bulk_dir("wikidata") / f"rice_dishes_{ver}.json").write_text(json.dumps({"base": base, "entities": ents}))

    def label(q, lang="en"):
        return (ents.get(q, {}).get("labels", {}).get(lang) or {}).get("value")

    def iso2(q):
        for c in ents.get(q, {}).get("claims", {}).get("P297", []):
            return c["mainsnak"].get("datavalue", {}).get("value")
        return None

    rows = []
    for q, v in base.items():
        e = ents.get(q, {})
        names = []
        for lang in LANGS:
            if label(q, lang):
                names.append((lang, label(q, lang), "label"))
            for a in e.get("aliases", {}).get(lang, []):
                names.append((lang, a["value"], "alias"))
        for site, sl in e.get("sitelinks", {}).items():
            if site.endswith("wiki") and site[:-4] in LANGS:
                names.append((site[:-4], sl["title"], "wikipedia_title"))
        rows.append((q, label(q) or label(q, "de"), [iso2(c) or label(c) for c in v["origin"]],
                     [label(m) for m in v["meat"]], bool(v["meat"]), v["classes"],
                     json.dumps([{"lang": lg, "name": n, "kind": k} for lg, n, k in names], ensure_ascii=False),
                     len(e.get("sitelinks", {}))))
    tbl = table_name(name, ver)
    with connect() as c:
        c.execute(f"""DROP TABLE IF EXISTS {tbl};
          CREATE TABLE {tbl} (qid text PRIMARY KEY, name_en text, origin_countries text[],
            meat_ingredients text[], has_meat boolean, classes text[], names jsonb, sitelink_count int)""")
        with c.cursor().copy(f"COPY {tbl} FROM STDIN") as cp:
            for row in rows:
                cp.write_row(row)
    register(name, ver, SPARQL, tbl, "Wikidata CC0", refresh_cadence="quarterly",
             meta={"dishes": len(rows)})
    console.print(f"[green]wikidata rice dishes:[/] {len(rows)}")
