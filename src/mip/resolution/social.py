"""Link social accounts to businesses with decision bands: auto-link above the upper threshold, reject below the
lower one, and send the grey zone to ops.match_review (domain 'social').

Evidence (core.social_link_candidate + fetched account data):
  own website links to the handle  +0.55   | OSM / Overture tag  +0.25 each
  handle ~ business name           +0.25   | account bio / website mentions the business domain  +0.30
  account bio mentions Berlin / the street +0.10
  handle claimed by > 2 businesses -0.60 (theme vendor, agency, platform)
"""

import re

from rapidfuzz import fuzz
from rich.console import Console

from mip.db import Jsonb, connect

console = Console()
UPPER, LOWER = 0.75, 0.40


def _handle_name_sim(handle: str, name_key: str | None) -> float:
    if not name_key:
        return 0.0
    h = re.sub(r"[._\-]+", " ", handle.lower())
    h = re.sub(r"\b(berlin|official|restaurant|de|bln)\b", " ", h).strip()
    return max(fuzz.partial_ratio(h.replace(" ", ""), name_key.replace(" ", "")), fuzz.token_set_ratio(h, name_key))


def resolve_social() -> dict:
    with connect() as c:
        cands = c.execute("""
            select c.business_id, c.platform, c.handle, c.evidence, c.businesses_claiming,
                   b.name, b.name_key, b.website_domain, b.street,
                   a.bio, a.website as account_website, a.display_name
            from core.social_link_candidate c
            join core.business b using (business_id)
            left join core.social_account a on a.platform = c.platform and a.handle = c.handle
            where c.platform in ('instagram', 'tiktok', 'facebook')""").fetchall()
    decisions: dict[str, tuple] = {}
    review = []
    for r in cands:
        ev = set(r["evidence"])
        score = 0.0
        score += 0.55 if "own_website" in ev else 0
        score += 0.25 * len(ev & {"osm_tag", "overture_socials"})
        sim = _handle_name_sim(r["handle"], r["name_key"])
        score += 0.25 if sim >= 75 else 0.1 if sim >= 60 else 0
        text = " ".join(filter(None, [r["bio"], r["account_website"], r["display_name"]])).lower()
        if r["website_domain"] and r["website_domain"] in text:
            score += 0.30
        if text and ("berlin" in text or (r["street"] and r["street"].lower()[:8] in text)):
            score += 0.10
        if r["businesses_claiming"] > 2:
            score -= 0.60
        score = max(0.0, min(1.0, score))
        key = f"{r['platform']}:{r['handle']}"
        evidence = {"evidence": sorted(ev), "handle_name_sim": sim, "claimed_by": r["businesses_claiming"],
                    "business": r["name"]}
        decision = "auto" if score >= UPPER else "rejected" if score < LOWER else "review"
        if key not in decisions or score > decisions[key][1]:
            decisions[key] = (r["business_id"], score, decision, evidence)
        if decision == "review":
            review.append((key, str(r["business_id"]), score, evidence))
    with connect() as c, c.transaction():
        manual = {r["account_key"] for r in c.execute("SELECT account_key FROM ops.social_assignment WHERE decision='manual'")}
        c.execute("DELETE FROM ops.social_assignment WHERE decision <> 'manual'")
        with c.cursor() as cur:
            cur.executemany(
                "INSERT INTO ops.social_assignment (account_key, business_id, score, decision, evidence)"
                " VALUES (%s,%s,%s,%s,%s)",
                [(k, b if d != "rejected" else None, s, d, Jsonb(e)) for k, (b, s, d, e) in decisions.items()
                 if k not in manual])
            cur.executemany(
                "INSERT INTO ops.match_review (domain, left_id, right_id, match_prob, features) VALUES"
                " ('social',%s,%s,%s,%s) ON CONFLICT (domain, left_id, right_id) DO UPDATE SET match_prob=EXCLUDED.match_prob",
                [(k, b, s, Jsonb(e)) for k, b, s, e in review])
    stats = {d: sum(1 for v in decisions.values() if v[2] == d) for d in ("auto", "review", "rejected")}
    console.print(f"[green]social links[/]: {stats}")
    return stats
