"""Text enrichment (non-ML, deterministic): language per text, and business mentions in media pages.

Mentions: distinctive business names (a rare word, >= 6 characters overall) are looked up as word n-grams of
each page, so matching is linear in text length instead of names x pages regex scans.
"""

import re
from collections import Counter, defaultdict

from lingua import Language, LanguageDetectorBuilder
from rich.console import Console

from mip.db import connect

console = Console()
LANGS = [Language.GERMAN, Language.ENGLISH, Language.ARABIC, Language.TURKISH, Language.URDU, Language.BENGALI,
         Language.HINDI, Language.PERSIAN, Language.RUSSIAN, Language.POLISH, Language.ITALIAN, Language.SPANISH,
         Language.FRENCH, Language.VIETNAMESE, Language.CHINESE, Language.UKRAINIAN, Language.GREEK]
WORD = re.compile(r"[\w'’&]+", re.UNICODE)


def _norm(s: str) -> list[str]:
    return [w.lower().replace("’", "'") for w in WORD.findall(s)]


def detect_languages(kinds: tuple[str, ...] = ("review", "page", "post")) -> int:
    det = LanguageDetectorBuilder.from_languages(*LANGS).with_preloaded_language_models().build()
    queries = {
        "review": "select review_id::text id, text from core.review r where text is not null and not exists "
                  "(select 1 from ops.text_language l where l.text_kind='review' and l.text_id=r.review_id::text)",
        "page": "select page_version_id::text id, left(main_text, 3000) text from core.web_page p where not exists "
                "(select 1 from ops.text_language l where l.text_kind='page' and l.text_id=p.page_version_id::text)",
        "post": "select post_id::text id, caption text from core.post p where caption is not null and not exists "
                "(select 1 from ops.text_language l where l.text_kind='post' and l.text_id=p.post_id::text)",
    }
    total = 0
    for kind in kinds:
        with connect() as c:
            rows = c.execute(queries[kind]).fetchall()
        out = []
        for r in rows:
            vals = det.compute_language_confidence_values(r["text"] or "")
            top = vals[0] if vals else None
            out.append((kind, r["id"], top.language.iso_code_639_1.name.lower() if top and top.value > 0.3 else None,
                        float(top.value) if top else None, "lingua-1"))
        with connect() as c, c.cursor() as cur:
            cur.executemany("INSERT INTO ops.text_language (text_kind, text_id, lang, confidence, detector)"
                            " VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", out)
        total += len(out)
        console.print(f"languages {kind}: {len(out):,}")
    return total


def find_mentions() -> int:
    with connect() as c:
        biz = c.execute("select business_id, name, name_key from core.business where in_market and status <> 'closed'"
                        " and name is not null").fetchall()
        pages = c.execute("select page_version_id, main_text from core.web_page where site_kind = 'media' and"
                          " main_text is not null").fetchall()
        corpus = c.execute("select main_text from core.web_page where main_text is not null").fetchall()
    df = Counter(t for b in biz for t in set((b["name_key"] or "").split()))
    # ordinary words ('teller', 'schmeckt', 'kiez') appear on many crawled pages: they cannot identify a business
    page_df = Counter(t for r in corpus for t in set(_norm(r["main_text"])))
    common = {t for t, n in page_df.items() if n > max(5, 0.01 * len(corpus))}
    needles: dict[tuple[str, ...], set] = defaultdict(set)
    for b in biz:
        toks = tuple(_norm(b["name"]))
        if len(" ".join(toks)) < 6 or not toks or len(toks) > 6:
            continue
        if not any(df.get(t, 0) <= 3 and len(t) >= 5 and t not in common for t in (b["name_key"] or "").split()):
            continue  # only names specific enough not to collide with ordinary words
        if len(toks) == 1 and toks[0] in common:
            continue
        needles[toks].add((b["business_id"], b["name"]))
    ambiguous = {k for k, v in needles.items() if len(v) > 2}  # same name at many places: chains handled by brand
    lengths = sorted({len(k) for k in needles}, reverse=True)
    rows = []
    for p in pages:
        text = p["main_text"]
        words = [(m.group(0).lower().replace("’", "'"), m.start()) for m in WORD.finditer(text)]
        tokens = [w for w, _ in words]
        seen = set()
        for n in lengths:
            for i in range(len(tokens) - n + 1):
                key = tuple(tokens[i:i + n])
                if key in needles and key not in ambiguous:
                    for bid, name in needles[key]:
                        if bid in seen:
                            continue
                        seen.add(bid)
                        off = words[i][1]
                        rows.append((p["page_version_id"], bid, name, off,
                                     text[max(0, off - 160): off + 200], "ngram-exact-1"))
    with connect() as c, c.cursor() as cur:
        cur.execute("TRUNCATE ops.text_mention")
        cur.executemany("INSERT INTO ops.text_mention (page_version_id, business_id, matched_name, char_offset, snippet,"
                        " matcher) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)
    console.print(f"[green]mentions[/]: {len(rows):,} across {len(pages):,} media pages ({len(needles):,} names searchable)")
    return len(rows)
