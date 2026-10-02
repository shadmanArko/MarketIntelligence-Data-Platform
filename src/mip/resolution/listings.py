"""Entity resolution: which listings on Wolt, Lieferando, Google Maps, OSM and Overture are one real business.

1. Features   normalised name, location, phone, website domain, street + number, cuisines, menu items,
              legal entity (VAT / register id) — built in Postgres from core tables.
2. Blocking   same / shifted H3 r8 cell, same phone, same domain, same postcode + name prefix.
3. Scoring    deterministic links for unambiguous evidence, then a Splink Fellegi-Sunter model trained
              without labels (EM). Shared menu items are the strongest kitchen signal.
4. Clustering union-find over edges above the threshold, with cannot-link constraints: a business never
              holds two listings of the same exclusive platform (Wolt, Lieferando, Google Maps) and never
              spans more than MAX_SPAN_M — this stops chain branches from chaining into one business.
5. Stable ids ops.business_assignment keeps every listing's business_id across runs; merges, splits and
              moves are written to ops.entity_changes, never silently re-keyed.
6. Review     a probability-stratified sample of pairs goes to ops.match_review for human labels
              (`mip resolve review`); gate 2 = precision >= 0.95 on those labels (`mip resolve evaluate`).
"""

import json
import math
import uuid
from collections import Counter, defaultdict

import duckdb
import splink.comparison_level_library as cll
import splink.comparison_library as cl
from rich.console import Console
from splink import Linker, SettingsCreator, block_on
from splink.backends.duckdb import DuckDBAPI

from mip.db import connect
from mip.settings import settings

console = Console()

EXCLUSIVE_PLATFORMS = {"wolt", "lieferando", "google_maps"}
MAX_SPAN_M = 400
GENERIC_DOMAINS = (
    "wolt.com", "lieferando.de", "ubereats.com", "uber.com", "facebook.com", "instagram.com", "google.com",
    "goo.gl", "linktr.ee", "tiktok.com", "business.site", "tischreservieren.com", "thefork.de", "opentable.de",
    "opentable.com", "quandoo.de", "yelp.de", "tripadvisor.de", "foodora.de", "deliveroo.de", "gastronovi.com",
    "resmio.com", "dish.co", "orderbird.com", "simplywww.de", "wixsite.com", "jimdo.com", "jimdofree.com",
    "site123.me", "webador.de", "squarespace.com", "netlify.app", "vercel.app", "forms.gle", "linkin.bio",
    "beacons.ai", "bit.ly", "t.me", "wa.me", "whatsapp.com", "youtube.com", "twitter.com", "x.com",
)

FEATURES_SQL = """
with menu as (
  select listing_id, array_agg(name_folded order by position) filter (where rn <= 300) as menu_tokens
  from (select listing_id, name_folded, position,
               row_number() over (partition by listing_id order by position) rn
        from core.offering where coalesce((attributes->>'drink')::boolean, false) = false) o
  group by 1
),
cuis as (select listing_id, array_agg(cuisine_id order by cuisine_id) as cuisines from core.listing_cuisine group by 1),
-- a phone / domain used by many listings or by more than two different names (malls, food courts,
-- call centres, franchise HQs) is not evidence that two listings are one business
phones as (select phone from core.listing where phone is not null group by 1
           having count(*) > 8 or count(distinct left(coalesce(name_key, lower(name)), 4)) > 2),
domains as (select website_domain from core.listing where website_domain is not null group by 1
            having count(*) > 60 or count(distinct left(coalesce(name_key, lower(name)), 4)) > 2)
select
  l.listing_key, l.platform, l.name,
  coalesce(l.name_key, lower(l.name))                                         as name_key,
  left(coalesce(l.name_key, lower(l.name)), 3)                                as name3,
  l.lat, l.lon, l.h3_r8,
  h3_lat_lng_to_cell(point(l.lon + 0.0035, l.lat + 0.0021), 8)::text          as h3_shift,
  case when l.phone in (select phone from phones) or length(l.phone) < 9 then null else l.phone end as phone,
  case when l.website_domain = any(%(generic)s) or l.website_domain in (select website_domain from domains)
       then null else l.website_domain end                                    as website_domain,
  l.postcode_resolved                                                         as postcode,
  nullif(regexp_replace(regexp_replace(lower(concat_ws(' ', unaccent(replace(replace(lower(l.street), 'ß', 'ss'), 'ü', 'ue')),
         l.house_number)), '(str\.|str\M|strasse)', 'strasse', 'g'), '[^a-z0-9 ]', '', 'g'), '')  as street_hn,
  coalesce(l.vat_number, l.legal_register_id)                                 as legal_key,
  c.cuisines, m.menu_tokens, l.status, l.in_market
from core.listing l
left join cuis c using (listing_id)
left join menu m using (listing_id)
where l.lat is not null and l.status <> 'test'
"""


def _haversine_m(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _features(con: duckdb.DuckDBPyConnection) -> int:
    with connect() as c:
        rows = c.execute(FEATURES_SQL, {"generic": list(GENERIC_DOMAINS)}).fetchall()
    import polars as pl

    df = pl.DataFrame(rows, infer_schema_length=None)
    con.register("features_pl", df.to_arrow())
    con.execute("CREATE OR REPLACE TABLE features AS SELECT * FROM features_pl")
    return len(df)


def _settings() -> SettingsCreator:
    name = cl.CustomComparison(
        output_column_name="name",
        comparison_levels=[
            # m fixed from domain knowledge: unsupervised EM over location-blocked pairs otherwise learns
            # "same building = same business" (malls, food halls) and stops penalising different names
            cll.NullLevel("name_key"),
            cll.ExactMatchLevel("name_key").configure(m_probability=0.50, fix_m_probability=True),
            cll.JaroWinklerLevel("name_key", 0.95).configure(m_probability=0.16, fix_m_probability=True),
            cll.CustomLevel("(length(name_key_l) >= 4 and length(name_key_r) >= 4 and "
                            "(contains(name_key_l, name_key_r) or contains(name_key_r, name_key_l)))",
                            "one name contains the other").configure(m_probability=0.14, fix_m_probability=True),
            cll.JaroWinklerLevel("name_key", 0.88).configure(m_probability=0.09, fix_m_probability=True),
            cll.JaccardLevel("name_key", 0.6).configure(m_probability=0.05, fix_m_probability=True),
            cll.JaroWinklerLevel("name_key", 0.75).configure(m_probability=0.04, fix_m_probability=True),
            cll.ElseLevel().configure(m_probability=0.02, fix_m_probability=True),
        ],
    )
    return SettingsCreator(
        link_type="dedupe_only",
        unique_id_column_name="listing_key",
        probability_two_random_records_match=1e-5,
        blocking_rules_to_generate_predictions=[
            block_on("h3_r8"),
            block_on("h3_shift"),
            block_on("phone"),
            block_on("website_domain"),
            block_on("postcode", "name3"),
        ],
        comparisons=[
            name,
            cl.DistanceInKMAtThresholds("lat", "lon", [0.025, 0.075, 0.2, 0.6]),
            cl.ExactMatch("phone"),
            cl.ExactMatch("website_domain"),
            cl.ExactMatch("street_hn"),
            cl.ExactMatch("legal_key"),
            cl.ArrayIntersectAtSizes("cuisines", [2, 1]),
            cl.ArrayIntersectAtSizes("menu_tokens", [12, 5, 2]),
        ],
        retain_matching_columns=True,
        retain_intermediate_calculation_columns=True,
    )


DETERMINISTIC_SQL = """
select l.listing_key as a, r.listing_key as b, 0.9999 as p, rule
from features l join features r on l.listing_key < r.listing_key
cross join lateral (select case
    when l.phone = r.phone and jaro_winkler_similarity(l.name_key, r.name_key) >= 0.75 then 'phone+name'
    when l.website_domain = r.website_domain and jaro_winkler_similarity(l.name_key, r.name_key) >= 0.75 then 'domain+name'
    when l.legal_key = r.legal_key and jaro_winkler_similarity(l.name_key, r.name_key) >= 0.85 then 'legal+name'
    when l.street_hn = r.street_hn and l.name_key = r.name_key then 'address+name'
  end as rule) x
where (l.phone = r.phone or l.website_domain = r.website_domain or l.legal_key = r.legal_key
       or (l.street_hn = r.street_hn and l.name_key = r.name_key))
  and rule is not null
  and 6371000 * 2 * asin(sqrt(pow(sin(radians(r.lat - l.lat) / 2), 2)
        + cos(radians(l.lat)) * cos(radians(r.lat)) * pow(sin(radians(r.lon - l.lon) / 2), 2))) < 150
"""


MIN_NAME_SIM = 60  # rapidfuzz token_set_ratio between every pair of names in a business


GENERIC_TOKEN_DF = 40   # a name token used by more than this many Berlin listings is generic ("coffee", "casa")
_TOKEN_DF: Counter = Counter()


def name_sim(a: str | None, b: str | None) -> float:
    """Token-set similarity, but only when the shared tokens include a distinctive one; names that share
    only common words ('coffee', 'pizza', 'casa') fall back to a strict whole-string ratio."""
    from rapidfuzz import fuzz

    if not a or not b:
        return 100.0  # missing name: no evidence against
    shared = set(a.split()) & set(b.split())
    if any(_TOKEN_DF[t] <= GENERIC_TOKEN_DF and len(t) >= 3 for t in shared):
        return fuzz.token_set_ratio(a, b)
    # only generic words in common: must be near-identical as whole strings ("coffee" vs "coffee fellows" fails)
    strict = max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b))
    return strict if strict >= 85 else 0.0


def address_conflict(a: str | None, b: str | None) -> bool:
    """Both addresses known and clearly different (another branch of a chain next door)."""
    from rapidfuzz import fuzz

    if not a or not b:
        return False
    num_a, num_b = a.rsplit(" ", 1)[-1], b.rsplit(" ", 1)[-1]
    if num_a[:1].isdigit() and num_b[:1].isdigit() and num_a.rstrip("abcdefg") != num_b.rstrip("abcdefg"):
        # different house number on a similar street: conflict only if the streets also match
        return fuzz.ratio(a.rsplit(" ", 1)[0], b.rsplit(" ", 1)[0]) >= 80 or fuzz.ratio(a, b) < 70
    return fuzz.ratio(a, b) < 70


class _UF:
    def __init__(self, items, platform, coords, names, addresses):
        self.parent = {i: i for i in items}
        self.members = {i: [i] for i in items}
        self.platforms = {i: Counter([platform[i]]) for i in items}
        self.platform, self.coords, self.names, self.addresses = platform, coords, names, addresses

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def can_union(self, a, b) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        pa, pb = self.platforms[ra], self.platforms[rb]
        if any(pa[p] and pb[p] for p in EXCLUSIVE_PLATFORMS):
            return False
        ma, mb = self.members[ra], self.members[rb]
        pairs = [(x, y) for x in ma for y in mb][:2500]
        if any(_haversine_m(self.coords[x], self.coords[y]) > MAX_SPAN_M for x, y in pairs):
            return False
        if any(address_conflict(self.addresses[x], self.addresses[y]) for x, y in pairs):
            return False
        # complete-linkage on names: stops a mall's shared phone from chaining its tenants together
        return all(name_sim(self.names[x], self.names[y]) >= MIN_NAME_SIM for x, y in pairs)

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if len(self.members[ra]) < len(self.members[rb]):
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.members[ra] += self.members.pop(rb)
        self.platforms[ra] += self.platforms.pop(rb)


def _assign_stable_ids(clusters: list[list[str]], resolution_run: uuid.UUID, probs: dict) -> dict:
    stats = Counter()
    with connect() as c:
        prev = {r["listing_key"]: r["business_id"] for r in
                c.execute("SELECT listing_key, business_id FROM ops.business_assignment").fetchall()}
        prev_sizes = Counter(prev.values())
        used: set = set()
        assignments: list[tuple] = []
        changes: list[tuple] = []
        # biggest clusters claim their previous id first
        for members in sorted(clusters, key=len, reverse=True):
            old = Counter(prev[m] for m in members if m in prev)
            candidates = [bid for bid, _ in old.most_common() if bid not in used]
            if candidates:
                bid = candidates[0]
                for other in [b for b in old if b != bid]:
                    changes.append((resolution_run, "merge", bid, other, None,
                                    {"members": len(members), "other_members_before": prev_sizes[other]}))
                    stats["merges"] += 1
                if old and old[bid] < prev_sizes[bid] and bid in used:
                    stats["splits"] += 1
            else:
                bid = uuid.uuid7() if hasattr(uuid, "uuid7") else uuid.uuid4()
                stats["new"] += 1
                if old:  # all previous ids already claimed: this is a split-off
                    changes.append((resolution_run, "split", bid, next(iter(old)), None, {"members": len(members)}))
                    stats["splits"] += 1
                else:
                    changes.append((resolution_run, "create", bid, None, None, {"members": len(members)}))
            used.add(bid)
            method = "singleton" if len(members) == 1 else "splink"
            for m in members:
                if m in prev and prev[m] != bid:
                    changes.append((resolution_run, "move", bid, prev[m], m, None))
                    stats["moves"] += 1
                assignments.append((m, bid, probs.get(m), method, resolution_run))
        with c.transaction():
            c.execute("TRUNCATE ops.business_assignment")
            with c.cursor() as cur:
                cur.executemany("INSERT INTO ops.business_assignment (listing_key, business_id, match_prob, method,"
                                " resolution_run) VALUES (%s,%s,%s,%s,%s)", assignments)
                cur.executemany("INSERT INTO ops.entity_changes (resolution_run, kind, business_id, other_business_id,"
                                " listing_id, detail) VALUES (%s,%s,%s,%s,%s,%s)", changes)
    stats["businesses"] = len(clusters)
    return dict(stats)


def _sample_review(con: duckdb.DuckDBPyConnection, n_merged: int = 150, n_near: int = 60) -> int:
    """Labels measure the decisions we ship: mostly cross-platform pairs inside one business (precision),
    plus high-scoring pairs that were kept apart (missed matches)."""
    with connect() as c:
        assign = c.execute("SELECT listing_key, business_id::text AS b FROM ops.business_assignment").fetchall()
    import pyarrow as pa

    con.register("assign_arrow", pa.table({"listing_key": [r["listing_key"] for r in assign],
                                           "b": [r["b"] for r in assign]}))
    con.execute("CREATE OR REPLACE TABLE assign AS SELECT * FROM assign_arrow")
    cols = """fl.listing_key, fr.listing_key, coalesce(s.match_probability, 1.0), fl.name, fr.name, fl.platform,
              fr.platform, fl.street_hn, fr.street_hn, fl.phone, fr.phone, fl.website_domain, fr.website_domain,
              round(6371000 * 2 * asin(sqrt(pow(sin(radians(fr.lat - fl.lat) / 2), 2)
                + cos(radians(fl.lat)) * cos(radians(fr.lat)) * pow(sin(radians(fr.lon - fl.lon) / 2), 2))))"""
    merged = con.execute(f"""
        select {cols} from assign al join assign ar on al.b = ar.b and al.listing_key < ar.listing_key
        join features fl on fl.listing_key = al.listing_key join features fr on fr.listing_key = ar.listing_key
        left join scored s on s.listing_key_l = fl.listing_key and s.listing_key_r = fr.listing_key
        where fl.platform <> fr.platform
        order by hash(fl.listing_key || fr.listing_key) limit {n_merged}""").fetchall()
    near = con.execute(f"""
        select {cols} from scored s join features fl on fl.listing_key = s.listing_key_l
        join features fr on fr.listing_key = s.listing_key_r
        join assign al on al.listing_key = fl.listing_key join assign ar on ar.listing_key = fr.listing_key
        where al.b <> ar.b and s.match_probability >= 0.5 and s.gamma_name >= 2
        order by hash(fl.listing_key || fr.listing_key) limit {n_near}""").fetchall()
    rows = merged + near
    with connect() as c, c.cursor() as cur:
        cur.executemany(
            "INSERT INTO ops.match_review (domain, left_id, right_id, match_prob, features) VALUES ('listing',%s,%s,%s,%s)"
            " ON CONFLICT (domain, left_id, right_id) DO UPDATE SET match_prob = EXCLUDED.match_prob,"
            " features = EXCLUDED.features",
            [(r[0], r[1], r[2], json.dumps({
                "name": [r[3], r[4]], "platform": [r[5], r[6]], "address": [r[7], r[8]], "phone": [r[9], r[10]],
                "domain": [r[11], r[12]], "distance_m": r[13]})) for r in rows])
    return len(rows)


def resolve(threshold: float = 0.9) -> dict:
    with connect() as c:
        rr = c.execute("INSERT INTO ops.resolution_runs (threshold) VALUES (%s) RETURNING resolution_run",
                       (threshold,)).fetchone()["resolution_run"]
    tmp = settings().data_dir / "cache" / "resolution.duckdb"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(tmp))
    n = _features(con)
    console.print(f"features: {n:,} listings")

    det = con.execute(DETERMINISTIC_SQL).fetchall()
    console.print(f"deterministic links: {len(det):,} ({dict(Counter(r[3] for r in det))})")

    db_api = DuckDBAPI(connection=con)
    sdf = db_api.register("features", table_name="features_splink")
    linker = Linker(sdf, _settings())
    linker.training.estimate_probability_two_random_records_match(
        [block_on("phone", "name_key"), block_on("website_domain", "name_key"), block_on("street_hn", "name_key")],
        recall=0.6)
    linker.training.estimate_u_using_random_sampling(max_pairs=5e6, seed=42)
    # EM only on blocks where true matches are common; never on pure location blocks
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("name_key"))
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("phone"))
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("website_domain"))
    pred = linker.inference.predict(threshold_match_probability=0.2)
    con.execute(f"CREATE OR REPLACE TABLE scored AS SELECT * FROM {pred.physical_name}")
    n_pairs = con.execute("SELECT count(*) FROM scored").fetchone()[0]
    console.print(f"scored pairs >= 0.2: {n_pairs:,}")

    # edges: deterministic + probabilistic above threshold, strongest first
    edges = {(a, b): p for a, b, p, _ in det}
    for a, b, p in con.execute(f"""
            SELECT listing_key_l, listing_key_r, match_probability FROM scored
            WHERE match_probability >= {threshold}
              AND (gamma_name >= 3 OR gamma_menu_tokens >= 2)  -- name agrees, or >= 5 shared menu items
            """).fetchall():
        key = (a, b) if a < b else (b, a)
        edges[key] = max(edges.get(key, 0), p)
    feats = con.execute("SELECT listing_key, platform, lat, lon, name_key, street_hn FROM features").fetchall()
    platform = {k: p for k, p, *_ in feats}
    coords = {k: (la, lo) for k, _, la, lo, *_ in feats}
    names = {k: nk for k, _, _, _, nk, _ in feats}
    addresses = {k: a for k, *_, a in feats}
    _TOKEN_DF.clear()
    _TOKEN_DF.update(t for nk in names.values() if nk for t in set(nk.split()))
    uf = _UF(list(platform), platform, coords, names, addresses)
    blocked = 0
    best_prob: dict[str, float] = defaultdict(float)
    for (a, b), p in sorted(edges.items(), key=lambda kv: -kv[1]):
        if uf.find(a) == uf.find(b):
            continue
        if uf.can_union(a, b):
            uf.union(a, b)
            best_prob[a] = max(best_prob[a], p)
            best_prob[b] = max(best_prob[b], p)
        else:
            blocked += 1
    clusters = list(uf.members.values())
    console.print(f"edges {len(edges):,}, blocked by cannot-link {blocked:,}, clusters {len(clusters):,}")

    stats = _assign_stable_ids(clusters, rr, best_prob)
    sampled = _sample_review(con)
    model = json.loads(json.dumps(linker.misc.save_model_to_json(), default=str))
    with connect() as c:
        c.execute("UPDATE ops.resolution_runs SET ended_at=now(), pairs_scored=%s, clusters=%s, model_json=%s"
                  " WHERE resolution_run=%s", (n_pairs, len(clusters), model, rr))
    from mip.resolution.brands import detect_brands

    detect_brands()
    sizes = Counter(min(len(m), 6) for m in clusters)
    console.print(f"[green]resolution {rr}[/]: {stats}; cluster sizes {dict(sorted(sizes.items()))};"
                  f" {sampled} pairs queued for review")
    return stats
