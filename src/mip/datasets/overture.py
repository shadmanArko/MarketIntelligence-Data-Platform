"""Overture Maps Places: monthly GeoParquet on S3, read by bounding box straight from DuckDB."""

import httpx

from mip.config import Market
from mip.datasets import already_loaded, console, duck, loader, portable_select, register, table_name
from mip.geo.grid import bbox

BUCKET = "s3://overturemaps-us-west-2/release"


def latest_release() -> str:
    cat = httpx.get("https://stac.overturemaps.org/catalog.json", timeout=30).json()
    return cat["latest"]


@loader("overture")
def load(market: Market, version: str | None = None) -> None:
    release = version or latest_release()
    name = "overture_places"
    if already_loaded(name, release):
        console.print(f"overture {release} already loaded")
        return
    tbl = table_name(name, release)
    minx, miny, maxx, maxy = bbox(market)
    con = duck()
    con.execute("SET s3_region='us-west-2'")
    src = f"{BUCKET}/{release}/theme=places/type=place/*"
    console.print(f"reading Overture {release} places in bbox {minx:.3f},{miny:.3f},{maxx:.3f},{maxy:.3f} ...")
    rel = f"read_parquet('{src}', filename=false, hive_partitioning=1, union_by_name=true)"
    sel = portable_select(con, rel)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE ov AS
        SELECT {sel} FROM {rel}
        WHERE bbox.xmin BETWEEN {minx} AND {maxx} AND bbox.ymin BETWEEN {miny} AND {maxy}
    """)
    n = con.execute("SELECT count(*) FROM ov").fetchone()[0]
    console.print(f"{n:,} Overture places in bbox; writing {tbl}")
    schema, t = tbl.split(".")
    con.execute(f'DROP TABLE IF EXISTS pg.{schema}."{t}"')
    con.execute(f'CREATE TABLE pg.{schema}."{t}" AS SELECT * FROM ov')
    register(name, release, f"{BUCKET}/{release}/theme=places/type=place/", tbl,
             "CDLA-Permissive-2.0 / Apache-2.0 per source", refresh_cadence="monthly",
             meta={"bbox": [minx, miny, maxx, maxy]})
