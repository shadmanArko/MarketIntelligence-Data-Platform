"""Quality report per run (feeds the promotion gates): status mix, volume vs previous run, completeness of key
fields, freshness, quarantine. Written to ops.quality_report; any failed check makes `mip report` exit 1."""

import typer
from rich.console import Console
from rich.table import Table

from mip.config import Market
from mip.db import connect

console = Console()

MAX_BAD_STATUS_SHARE = 0.20
BAD_STATUS_OVERRIDES = {"web_crawl": 0.60, "tiktok": 0.70, "instagram_graph": 0.50}  # the open web is messy
MAX_VOLUME_DROP = 0.30
MAX_FRESHNESS_H = 24 * 14

# staging view -> fields that must be mostly filled (min share)
COMPLETENESS = {
    "stg_wolt__venue_listing": {"name": 0.99, "lat": 0.99, "rating_value": 0.5},
    "stg_wolt__venue_static": {"name": 0.99, "address_line": 0.7, "legal_name": 0.6},
    "stg_wolt__menu_item": {"name": 0.99, "price": 0.95},
    "stg_lieferando__restaurant_listing": {"name": 0.99, "lat": 0.99, "postcode": 0.95},
    "stg_lieferando__manifest": {"name": 0.99, "vat_number": 0.5, "phone": 0.8},
    "stg_lieferando__menu_item": {"name": 0.99, "price": 0.95},
    "stg_lieferando__review": {"rating_value": 0.99, "posted_at": 0.99},
    "stg_google_maps__place": {"name": 0.99, "lat": 0.99, "address_line": 0.8},
}


def _record(c, run_id, market_id, source, entity, metric, value, previous, passed, detail=""):
    c.execute("INSERT INTO ops.quality_report (run_id, market_id, source, entity_type, metric, value, previous, passed,"
              " detail) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
              (run_id, market_id, source, entity, metric, value, previous, passed, detail))


def run_report(market: Market) -> None:
    failures = 0
    t = Table("source", "entity", "check", "value", "previous", "ok")
    with connect() as c:
        # 1. status mix + volume per (source, entity) for each source's latest run vs the one before
        runs = c.execute("""
            select o.source, o.entity_type, o.run_id, count(*) n, max(o.fetched_at) last, r.status as run_status
            from raw.observations o join ops.runs r using (run_id)
            where o.market_id = %s group by 1, 2, 3, 6""", (market.id,)).fetchall()
        # current state: the latest observation of every entity (a fixed 400 no longer counts)
        status_now = {(r["source"], r["entity_type"]): r for r in c.execute("""
            select source, entity_type, count(*) n, count(*) filter (where http_status not between 200 and 299) bad
            from (select distinct on (source, entity_type, natural_key) source, entity_type, http_status
                  from raw.observations where market_id = %s
                  order by source, entity_type, natural_key, fetched_at desc) x
            group by 1, 2""", (market.id,)).fetchall()}
        by_key: dict = {}
        for r in runs:
            by_key.setdefault((r["source"], r["entity_type"]), []).append(r)
        for (src, ent), rs in sorted(by_key.items()):
            rs.sort(key=lambda r: r["last"])
            cur = rs[-1]
            sn = status_now.get((src, ent), {"n": 0, "bad": 0})
            total_n, total_bad = sn["n"], sn["bad"]
            share = total_bad / total_n if total_n else 0
            ok = share <= BAD_STATUS_OVERRIDES.get(src, MAX_BAD_STATUS_SHARE)
            _record(c, cur["run_id"], market.id, src, ent, "bad_status_share", share, None, ok,
                    f"{total_bad}/{total_n} non-2xx")
            t.add_row(src, ent, "non-2xx share", f"{share:.1%}", "", "✓" if ok else "✗")
            failures += not ok
            done = [r for r in rs if r["run_status"] == "succeeded"]
            if len(done) > 1:
                cur, prev = done[-1], done[-2]
                drop = 1 - cur["n"] / prev["n"] if prev["n"] else 0
                ok = drop <= MAX_VOLUME_DROP or cur["n"] < 50  # small follow-up runs are not comparable
                _record(c, cur["run_id"], market.id, src, ent, "row_count", cur["n"], prev["n"], ok)
                t.add_row(src, ent, "rows vs prev run", str(cur["n"]), str(prev["n"]), "✓" if ok else "✗")
                failures += not ok
            age_h = c.execute("select extract(epoch from now() - %s::timestamptz) / 3600 h", (cur["last"],)).fetchone()["h"]
            ok = age_h <= MAX_FRESHNESS_H
            _record(c, cur["run_id"], market.id, src, ent, "freshness_h", float(age_h), None, ok)
            failures += not ok
        # 2. completeness of key fields in staging
        for view, fields in COMPLETENESS.items():
            exists = c.execute("select to_regclass(%s) r", (f"staging.{view}",)).fetchone()["r"]
            if not exists:
                continue
            sel = ", ".join(f"avg(({f}) is not null::int)::float8 as {f}" for f in fields)
            row = c.execute(f"select count(*) n, {sel} from staging.{view}").fetchone()
            for f, minimum in fields.items():
                v = row[f] if row["n"] else 0.0
                ok = row["n"] > 0 and v >= minimum
                _record(c, None, market.id, view.split("__")[0].removeprefix("stg_"), view, f"completeness:{f}",
                        v, minimum, ok, f"{row['n']} rows")
                t.add_row(view.removeprefix("stg_"), "", f"filled {f}", f"{v:.1%}" if row["n"] else "no rows",
                          f">= {minimum:.0%}", "✓" if ok else "✗")
                failures += not ok
        # 3. quarantine
        for r in c.execute("select source, entity_type, count(*) n from ops.quarantine group by 1, 2"):
            _record(c, None, market.id, r["source"], r["entity_type"], "quarantined", r["n"], None, True)
            t.add_row(r["source"], r["entity_type"], "quarantined", str(r["n"]), "", "·")
    console.print(t)
    console.print(f"[{'red' if failures else 'green'}]{failures} failed check(s)[/]")
    if failures:
        raise typer.Exit(1)
