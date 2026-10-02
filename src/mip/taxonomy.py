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
