"""Social-content sources, occasion calendar and content tagging."""

import json
from datetime import date
from pathlib import Path

from mip.connectors.berlin_events import Feed
from mip.connectors.reddit_archive import Page, RedditArchive
from mip.core.types import EntityRef
from mip.datasets.occasions import _hijri_range, _rule_days
from mip.enrich.content import Dictionary, fold

FX = Path(__file__).parent / "fixtures"


class _Resp:
    def __init__(self, body):
        self.body, self.status = body, 200

    def json(self):
        return self.body


def test_reddit_pages_dedupe_and_hash_authors(monkeypatch):
    posts = json.loads((FX / "reddit_archive" / "posts.json").read_text())["data"]
    for p in posts:
        p["author"] = "someone"
    pages = [{"data": posts * 20}, {"data": posts[:2]}]   # 100 rows (5 unique) then a short last page
    conn = RedditArchive.__new__(RedditArchive)
    conn.http = type("H", (), {"get": lambda self, *a, **k: _Resp(pages.pop(0))})()
    monkeypatch.setattr("mip.connectors.reddit_archive.hash_fields",
                        lambda obj, fields, ns: obj.update({f: "h:x" for f in fields if f in obj}) or obj)
    recs = list(conn.fetch(EntityRef("posts_month", "berlin|2025-03", {"subreddit": "berlin", "month": "2025-03"})))
    assert len(recs) == 1   # second page only repeats already-seen ids
    Page.model_validate(recs[0].payload)
    assert len(recs[0].payload["posts"]) == len({p["id"] for p in posts})
    assert all(p["author"] == "h:x" for p in recs[0].payload["posts"])


def test_berlin_events_contract():
    body = json.loads((FX / "berlin_events" / "street_festivals.json").read_text())
    Feed.model_validate({"feed": "street_festivals", **body})
    assert all({"bezeichnung", "von", "bis", "bezirk"} <= set(e) for e in body["index"])


def test_occasion_rules():
    ramadan = _hijri_range(2027, [9, 1], [9, 30])
    assert ramadan[0] == date(2027, 2, 8) and len(ramadan) in (29, 30)
    assert _rule_days({"kind": "easter", "offset": 47, "days": 4}, 2027)[0] == date(2027, 5, 14)  # Karneval der Kulturen
    assert _rule_days({"kind": "nth_weekday", "month": 5, "weekday": 6, "n": 2}, 2027) == [date(2027, 5, 9)]
    assert _rule_days({"kind": "nowruz_last_tuesday"}, 2027)[0].weekday() == 1
    assert _rule_days({"kind": "persian", "date": [9, 30]}, 2026) == [date(2026, 12, 21)]          # Yalda
    assert len(_rule_days({"kind": "month_end"}, 2027)) == 12


def test_content_dictionary_matches_across_scripts():
    d = Dictionary()
    d.add("কাচ্চি বিরিয়ানি", "dish", "kacchi_biryani")
    d.add("Kurban Bayramı", "occasion", "eid_al_adha")
    d.add("海南鸡饭", "dish", "hainan_chicken_rice")
    d.add("im test", "cue", "review_test")
    text = "Kurban bayrami özel: কাচ্চি বিরিয়ানি im Test! 海南鸡饭 too"
    got = {(t, i) for t, i, _ in d.match(text)}
    assert got == {("dish", "kacchi_biryani"), ("occasion", "eid_al_adha"), ("dish", "hainan_chicken_rice"),
                   ("cue", "review_test")}
    assert fold("Döner Größe") == "doener groesse"
