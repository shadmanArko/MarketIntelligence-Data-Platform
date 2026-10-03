"""Taxonomy YAML -> dbt seeds. The fold() here must match the dbt `fold` macro (lower, ä->ae, accents off)."""

import csv
import unicodedata

import yaml
from rich.console import Console

from mip.config import Market
from mip.settings import ROOT

SEEDS = ROOT / "dbt" / "seeds"
console = Console()


def fold(s: str) -> str:
    s = " ".join(s.lower().split())
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def load_taxonomy(market: Market) -> dict:
    return yaml.safe_load(market.path(market.taxonomy).read_text())


def export_seeds(market: Market) -> None:
    tax = load_taxonomy(market)
    SEEDS.mkdir(parents=True, exist_ok=True)
    rows = []
    for cid, spec in tax["cuisines"].items():
        for tag in {cid.replace("_", " "), *spec["tags"]}:
            rows.append({"tag": fold(tag), "cuisine_id": cid, "cuisine_group": spec["group"]})
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda r: (r["tag"], r["cuisine_id"])):
        if r["tag"] not in seen:
            seen.add(r["tag"])
            uniq.append(r)
    with (SEEDS / "cuisine_map.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, ["tag", "cuisine_id", "cuisine_group"])
        w.writeheader()
        w.writerows(uniq)
    drows = []
    # order matters: specific dishes (e.g. kacchi_biryani) are listed before generic ones (biryani)
    for prio, (did, patterns) in enumerate(tax["dishes"].items()):
        for p in patterns:
            drows.append({"dish_id": did, "pattern": fold(p), "priority": prio})
    with (SEEDS / "dish_map.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, ["dish_id", "pattern", "priority"])
        w.writeheader()
        w.writerows(drows)
    console.print(f"[green]seeds:[/] {len(uniq)} cuisine tags, {len(drows)} dish patterns")


def load_yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / "taxonomies" / name).read_text())


def _write(name: str, header: list[str], rows: list[dict]) -> None:
    with (SEEDS / name).open("w", newline="") as f:
        w = csv.DictWriter(f, header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def export_audience_seeds() -> None:
    """communities.yaml + occasions.yaml -> community, community_country, community_dish, community_greeting,
    occasion_type seeds. Native scripts are kept as-is (UTF-8)."""
    com, occ = load_yaml("communities.yaml")["communities"], load_yaml("occasions.yaml")
    c_rows, cc_rows, d_rows, g_rows = [], [], [], []
    for cid, c in com.items():
        c_rows.append({"community_id": cid, "label": c["label"], "languages": "|".join(c.get("languages", [])),
                       "scripts": "|".join(c.get("scripts", [])), "religion_mix": "|".join(c.get("religion_mix", [])),
                       "moon_offset": c.get("moon_offset", 0), "afs_citizenship": "|".join(c.get("afs_citizenship", [])),
                       "afs_origin": "|".join(c.get("afs_origin", [])), "notes": c.get("notes", "")})
        for cc in c.get("countries", []):
            cc_rows.append({"community_id": cid, "country": cc})
        for d in c.get("dishes", []):
            d_rows.append({"community_id": cid, "dish_id": d["id"], "native_name": d["native"],
                           "translit": d["translit"], "english": d["en"], "needs_review": bool(d.get("review"))})
        for occasion, g in (c.get("greetings") or {}).items():
            g_rows.append({"community_id": cid, "greeting_key": occasion, "text": g["text"],
                           "translit": g["translit"], "needs_review": bool(g.get("review"))})
    o_rows = [{"occasion_type": k, "food_role": v["food_role"], "lead_days": v["lead_days"], "tone": v["tone"],
               "holiday_name_regex": v.get("match", "")} for k, v in occ["types"].items()]
    _write("community.csv", list(c_rows[0]), c_rows)
    _write("community_country.csv", ["community_id", "country"], cc_rows)
    _write("community_dish.csv", list(d_rows[0]), d_rows)
    _write("community_greeting.csv", list(g_rows[0]), g_rows)
    _write("occasion_type.csv", list(o_rows[0]), o_rows)
    console.print(f"[green]audience seeds:[/] {len(c_rows)} communities, {len(cc_rows)} countries, {len(d_rows)} dishes,"
                  f" {len(g_rows)} greetings, {len(o_rows)} occasion types")
