"""Content tags (deterministic dictionary matching, no ML): which dishes, communities, occasions and format cues a
post / video / comment talks about. Writes ops.content_tag; dbt joins it into core.content_tag and the ml layer.

Dictionaries:
  dish       community dishes from config/taxonomies/communities.yaml (native name, transliteration, id)
  community  community labels and dish matches (a kabsa post is an Arab-community post)
  rice_dish  every Wikidata rice dish name (labels, aliases, Wikipedia titles in 44 languages), >= 4 characters
  occasion   occasions.yaml `keywords`
  cue        config/keywords/social_content.yaml `cues` (format / angle words)
Text is folded (lowercase, umlauts transliterated, accents and combining marks removed) on both sides, matched as
word sequences; for scripts written without spaces (CJK, Thai, Japanese) needles are matched as substrings.
"""

import re
import unicodedata
from collections import defaultdict

import yaml
from rich.console import Console

from mip.db import connect
from mip.settings import ROOT

console = Console()
MATCHER = "dict-v1"
WORD = re.compile(r"\w+", re.UNICODE)
NOSPACE = re.compile(r"[฀-๿぀-ヿ㐀-鿿가-힯]")
GENERIC = {"curry", "rice", "reis", "pilaf", "pulao", "pilav", "fried rice", "rice dish", "rice pudding", "bowl", "dum"}


def fold(s: str) -> str:
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("ı", "i")):
        s = s.replace(a, b)
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def _toks(s: str) -> tuple[str, ...]:
    return tuple(WORD.findall(fold(s)))


class Dictionary:
    def __init__(self) -> None:
        self.needles: dict[tuple[str, ...], set[tuple[str, str, str]]] = defaultdict(set)
        self.substr: list[tuple[str, tuple[str, str, str]]] = []

    def add(self, phrase: str, tag_type: str, tag_id: str) -> None:
        phrase = (phrase or "").strip()
        if len(phrase) < 2:
            return
        if NOSPACE.search(phrase):
            self.substr.append((fold(phrase), (tag_type, tag_id, phrase)))
            return
        t = _toks(phrase)
        if t and len(t) <= 6:
            self.needles[t].add((tag_type, tag_id, phrase))

    def match(self, text: str) -> set[tuple[str, str, str]]:
        out: set[tuple[str, str, str]] = set()
        if not text:
            return out
        toks = _toks(text)
        if not hasattr(self, "_lengths"):
            self._lengths = sorted({len(k) for k in self.needles})
        for n in self._lengths:
            for i in range(len(toks) - n + 1):
                hit = self.needles.get(toks[i:i + n])
                if hit:
                    out |= hit
        if self.substr and NOSPACE.search(text):
            f = fold(text)
            out |= {v for s, v in self.substr if s in f}
        return out


def build_dictionary() -> Dictionary:
    tax = ROOT / "config" / "taxonomies"
    com = yaml.safe_load((tax / "communities.yaml").read_text())["communities"]
    occ = yaml.safe_load((tax / "occasions.yaml").read_text())
    cues = yaml.safe_load((ROOT / "config" / "keywords" / "social_content.yaml").read_text()).get("cues", {})
    d = Dictionary()
    for cid, c in com.items():
        for part in re.split(r"\s*/\s*", c["label"]):
            d.add(part, "community", cid)
        for dish in c.get("dishes", []):
            for name in {dish["native"], dish["translit"], dish["id"].replace("_", " ")}:
                for alt in re.split(r"\s*/\s*", name):
                    if fold(alt) not in GENERIC:
                        d.add(alt, "dish", dish["id"])
                        d.add(alt, "community", cid)
    for t, words in (occ.get("keywords") or {}).items():
        for w in words:
            d.add(str(w), "occasion", t)
    for cue, words in cues.items():
        for w in words:
            d.add(str(w), "cue", cue)
    with connect() as c:
        tbl = c.execute("select raw_table from ops.datasets where name = 'wikidata_rice_dishes'"
                        " order by loaded_at desc limit 1").fetchone()["raw_table"]
        rows = c.execute(f"select qid, n ->> 'name' as name from {tbl}, jsonb_array_elements(names) n").fetchall()
    for r in rows:
        name = re.sub(r"\s*\(.*\)$", "", r["name"] or "")
        if len(name) >= 4 and fold(name) not in GENERIC:
            d.add(name, "rice_dish", r["qid"])
    d.add("biryani", "dish", "biryani")
    d.add("biriyani", "dish", "biryani")
    d.add("বিরিয়ানি", "dish", "biryani")
    d.add("بریانی", "dish", "biryani")
    d.add("बिरयानी", "dish", "biryani")
    return d


QUERIES = {
    "post": "select post_id::text id, concat_ws(' ', title, caption, array_to_string(tags, ' ')) text from core.post",
    "comment": "select comment_id id, text from staging.stg_youtube__comment where text is not null",
}


def tag_content(kinds: tuple[str, ...] = ("post", "comment")) -> int:
    d = build_dictionary()
    console.print(f"dictionary: {sum(len(v) for v in d.needles.values()):,} phrases, {len(d.substr):,} substrings")
    total = 0
    for kind in kinds:
        rows_out = []
        with connect() as c:
            try:
                rows = c.execute(QUERIES[kind]).fetchall()
            except Exception as e:   # staging view not built yet
                console.print(f"[yellow]{kind}: {e}[/]")
                continue
        for r in rows:
            for tag_type, tag_id, phrase in d.match(r["text"]):
                rows_out.append((kind, r["id"], tag_type, tag_id, phrase, MATCHER))
        uniq = {(k, i, t, g): (k, i, t, g, p, m) for k, i, t, g, p, m in rows_out}
        with connect() as c:
            c.execute("delete from ops.content_tag where text_kind = %s", (kind,))
            with c.cursor().copy("COPY ops.content_tag (text_kind, text_id, tag_type, tag_id, matched, matcher)"
                                 " FROM STDIN") as cp:
                for row in uniq.values():
                    cp.write_row(row)
        total += len(uniq)
        console.print(f"[green]content tags {kind}[/]: {len(uniq):,} tags on {len(rows):,} texts")
    return total
