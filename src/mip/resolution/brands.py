"""Chains: a brand that appears at several locations gets a brand_id, so branch- and brand-level analysis both work."""

import uuid

from rich.console import Console

from mip.db import connect

console = Console()
MIN_LOCATIONS = 3

SQL = """
with tok as (  -- how common each name word is across Berlin: 'pizza', 'sushi', 'coffee' are not brands
  select t, count(*) df from core.listing, unnest(string_to_array(name_key, ' ')) t group by 1
),
b as (
  select a.business_id,
         max(l.brand_name) filter (where l.brand_name is not null) as platform_brand,
         mode() within group (order by l.name_key) as name_brand
  from ops.business_assignment a join core.listing l using (listing_key)
  where l.in_market
  group by 1
),
k as (
  select business_id,
         lower(regexp_replace(unaccent(coalesce(platform_brand, name_brand)), '[^a-zA-Z0-9]+', ' ', 'g')) as brand_key,
         platform_brand is not null as from_platform
  from b where coalesce(platform_brand, name_brand) is not null
),
keys as (select brand_key, array_agg(business_id) businesses, bool_or(from_platform) from_platform
         from k where length(brand_key) >= 3 group by 1 having count(*) >= %(min)s),
distinctive as (  -- name-derived keys need at least one distinctive word
  select distinct kk.brand_key from keys kk, unnest(string_to_array(kk.brand_key, ' ')) w
  join tok on tok.t = w where tok.df <= 60 and length(w) >= 3
)
select keys.* from keys where from_platform or brand_key in (select brand_key from distinctive)
"""


def canonical_keys(keys: list[str]) -> dict[str, str]:
    """'domino s pizza' -> 'domino s', 'brotmeisterei steinecke' -> 'steinecke': a key that contains a shorter
    brand key as whole tokens (prefix or suffix) folds into it."""
    by_len = sorted(set(keys), key=len)
    canon = {k: k for k in by_len}
    for i, k in enumerate(by_len):
        toks = k.split()
        for shorter in by_len[:i]:
            st = shorter.split()
            if len(st) < len(toks) and len(shorter) >= 4 and (toks[: len(st)] == st or toks[-len(st):] == st):
                canon[k] = canon[shorter]
                break
    return canon


def detect_brands() -> int:
    with connect() as c:
        prev = {r["brand_name"]: r["brand_id"] for r in c.execute(
            "SELECT DISTINCT ON (brand_name) brand_name, brand_id FROM ops.brand_assignment")}
        rows = c.execute(SQL, {"min": MIN_LOCATIONS}).fetchall()
        canon = canonical_keys([r["brand_key"] for r in rows])
        merged: dict[str, list] = {}
        for r in rows:
            merged.setdefault(canon[r["brand_key"]], []).extend(r["businesses"])
        out = []
        for key, businesses in merged.items():
            bid = prev.get(key) or uuid.uuid4()
            out += [(b, bid, key) for b in businesses]
        rows = list(merged)
        with c.transaction():
            c.execute("TRUNCATE ops.brand_assignment")
            with c.cursor() as cur:
                cur.executemany("INSERT INTO ops.brand_assignment (business_id, brand_id, brand_name) VALUES (%s,%s,%s)"
                                " ON CONFLICT (business_id) DO NOTHING", out)
    console.print(f"[green]brands:[/] {len(rows)} chains covering {len(out)} businesses")
    return len(rows)
