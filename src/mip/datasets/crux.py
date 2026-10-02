"""Chrome UX Report popularity rank buckets per origin and country (monthly), via the public CrUX top-lists
export (github.com/zakird/crux-top-lists) — same data as the BigQuery `chrome-ux-report` rank, no GCP needed.
Absent = below the smallest public bucket, which is itself a signal (the model keeps it as NULL + flag)."""

import gzip
import re

import httpx

from mip.config import Market
from mip.datasets import already_loaded, bulk_dir, console, loader, register
from mip.db import connect

REPO = "https://api.github.com/repos/zakird/crux-top-lists/contents/data/country/{cc}"
RAW = "https://raw.githubusercontent.com/zakird/crux-top-lists/main/data/country/{cc}/{f}"


@loader("crux")
def load(market: Market, version: str | None = None) -> None:
    cc = str(market.source("crux").opt("country", "de")).lower()
    files = sorted(f["name"] for f in httpx.get(REPO.format(cc=cc), timeout=60).json()
                   if re.fullmatch(r"\d{6}\.csv\.gz", f["name"]))
    months = files[-int(market.source("crux").opt("months", 12)):] if not version else [f"{version}.csv.gz"]
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS raw.ds_crux_rank (
                       country text NOT NULL, yyyymm text NOT NULL, origin text NOT NULL, rank_bucket integer NOT NULL,
                       PRIMARY KEY (country, yyyymm, origin))""")
    for f in months:
        ym = f[:6]
        name = f"crux_rank_{cc}"
        if already_loaded(name, ym):
            continue
        path = bulk_dir("crux") / f"{cc}_{f}"
        if not path.exists():
            r = httpx.get(RAW.format(cc=cc, f=f), timeout=300, follow_redirects=True)
            r.raise_for_status()
            path.write_bytes(r.content)
        lines = gzip.decompress(path.read_bytes()).decode().splitlines()
        with connect() as c:
            c.execute("DELETE FROM raw.ds_crux_rank WHERE country=%s AND yyyymm=%s", (cc, ym))
            with c.cursor().copy("COPY raw.ds_crux_rank (country, yyyymm, origin, rank_bucket) FROM STDIN") as cp:
                for ln in lines[1:]:
                    origin, _, rank = ln.rpartition(",")
                    if rank.isdigit():
                        cp.write_row((cc, ym, origin, int(rank)))
        register(name, ym, RAW.format(cc=cc, f=f), "raw.ds_crux_rank", "CrUX: CC BY 4.0 (Google)",
                 refresh_cadence="monthly", meta={"rows": len(lines) - 1})
    console.print(f"[green]crux {cc}[/]: {len(months)} months")
