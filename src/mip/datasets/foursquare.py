"""Foursquare Open Source Places (Hugging Face, gated; HF_TOKEN), clipped to the market bbox via DuckDB."""

import httpx

from mip.config import Market
from mip.datasets import already_loaded, console, duck, loader, portable_select, register, table_name
from mip.geo.grid import bbox
from mip.settings import settings

REPO = "foursquare/fsq-os-places"


def latest_release(token: str) -> str:
    r = httpx.get(f"https://huggingface.co/api/datasets/{REPO}/tree/main/release",
                  headers={"Authorization": f"Bearer {token}"}, timeout=60)
    r.raise_for_status()
    return sorted(x["path"].split("dt=")[1] for x in r.json() if "dt=" in x["path"])[-1]


@loader("foursquare")
def load(market: Market, version: str | None = None) -> None:
    token = settings().hf_token
    if not token:
        raise SystemExit("set HF_TOKEN in .env (access to foursquare/fsq-os-places granted on Hugging Face)")
    release = version or latest_release(token)
    name = "foursquare_os_places"
    if already_loaded(name, release):
        console.print(f"foursquare {release} already loaded")
        return
    minx, miny, maxx, maxy = bbox(market)
    con = duck()
    con.execute(f"CREATE OR REPLACE SECRET hf (TYPE huggingface, TOKEN '{token}')")
    src = f"hf://datasets/{REPO}/release/dt={release}/places/parquet/*.parquet"
    rel = f"read_parquet('{src}', union_by_name=true)"
    sel = portable_select(con, rel, geometry_cols=("geom",))
    console.print(f"scanning Foursquare {release} for bbox {minx:.3f},{miny:.3f},{maxx:.3f},{maxy:.3f} ...")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE fsq AS SELECT {sel} FROM {rel}
                    WHERE longitude BETWEEN {minx} AND {maxx} AND latitude BETWEEN {miny} AND {maxy}""")
    n = con.execute("SELECT count(*) FROM fsq").fetchone()[0]
    tbl = table_name(name, release)
    schema, t = tbl.split(".")
    con.execute(f'DROP TABLE IF EXISTS pg.{schema}."{t}"')
    con.execute(f'CREATE TABLE pg.{schema}."{t}" AS SELECT * FROM fsq')
    console.print(f"{n:,} Foursquare places in bbox -> {tbl}")
    register(name, release, f"https://huggingface.co/datasets/{REPO}", tbl, "Apache-2.0 (Foursquare OS Places)",
             refresh_cadence="monthly", meta={"bbox": [minx, miny, maxx, maxy]})
