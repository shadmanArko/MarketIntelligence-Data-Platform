"""Reference vocabularies: Wikidata dishes and cuisines (CC0) to seed / extend the dish and cuisine taxonomies."""

from datetime import date

import httpx

from mip.config import Market
from mip.datasets import already_loaded, console, loader, register
from mip.db import connect

WDQS = "https://query.wikidata.org/sparql"
DISHES = """
SELECT ?item ?en ?de ?bn ?ur ?ar ?tr (GROUP_CONCAT(DISTINCT ?cuisineLabel; separator="|") AS ?cuisines)
       (GROUP_CONCAT(DISTINCT ?countryLabel; separator="|") AS ?countries) WHERE {
  { ?item wdt:P31 wd:Q746549 } UNION { ?item wdt:P279 wd:Q746549 } UNION { ?item wdt:P31/wdt:P279 wd:Q746549 }
  OPTIONAL { ?item rdfs:label ?en FILTER(lang(?en)="en") }
  OPTIONAL { ?item rdfs:label ?de FILTER(lang(?de)="de") }
  OPTIONAL { ?item rdfs:label ?bn FILTER(lang(?bn)="bn") }
  OPTIONAL { ?item rdfs:label ?ur FILTER(lang(?ur)="ur") }
  OPTIONAL { ?item rdfs:label ?ar FILTER(lang(?ar)="ar") }
  OPTIONAL { ?item rdfs:label ?tr FILTER(lang(?tr)="tr") }
  OPTIONAL { ?item wdt:P2012 ?cuisine . ?cuisine rdfs:label ?cuisineLabel FILTER(lang(?cuisineLabel)="en") }
  OPTIONAL { ?item wdt:P495 ?country . ?country rdfs:label ?countryLabel FILTER(lang(?countryLabel)="en") }
  FILTER(BOUND(?en) || BOUND(?de))
} GROUP BY ?item ?en ?de ?bn ?ur ?ar ?tr
"""


@loader("wikidata")
def load(market: Market, version: str | None = None) -> None:
    ver = version or date.today().isoformat()
    name = "wikidata_dishes"
    if already_loaded(name, ver):
        console.print("wikidata already loaded")
        return
    r = httpx.post(WDQS, data={"query": DISHES}, timeout=300,
                   headers={"Accept": "application/sparql-results+json", "User-Agent": "mip-market-intel/0.1"})
    r.raise_for_status()
    rows = r.json()["results"]["bindings"]

    def v(b, k):
        return b.get(k, {}).get("value") or None

    with connect() as c:
        c.execute("""DROP TABLE IF EXISTS raw.ds_wikidata_dishes;
          CREATE TABLE raw.ds_wikidata_dishes (qid text PRIMARY KEY, label_en text, label_de text, label_bn text,
            label_ur text, label_ar text, label_tr text, cuisines text[], countries text[], ingredients text[])""")
        with c.cursor().copy("COPY raw.ds_wikidata_dishes FROM STDIN") as cp:
            seen = set()
            for b in rows:
                qid = v(b, "item").rsplit("/", 1)[1]
                if qid in seen:
                    continue
                seen.add(qid)
                split = lambda x: [s for s in (x or "").split("|") if s] or None  # noqa: E731
                cp.write_row((qid, v(b, "en"), v(b, "de"), v(b, "bn"), v(b, "ur"), v(b, "ar"), v(b, "tr"),
                              split(v(b, "cuisines")), split(v(b, "countries")), None))
    register(name, ver, WDQS, "raw.ds_wikidata_dishes", "CC0", refresh_cadence="quarterly")
