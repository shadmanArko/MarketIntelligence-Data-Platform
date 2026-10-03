"""TripAdvisor European Restaurants (Kaggle, scraped May 2021): the Berlin rows as a 2021 baseline —
which restaurants existed then, their ratings / review counts / awards, to measure survival and rating change."""

import subprocess
import zipfile
from datetime import date

from mip.config import Market
from mip.datasets import already_loaded, bulk_dir, console, duck, loader, register, sha256_file
from mip.geo.grid import bbox

DATASET = "stefanoleone992/tripadvisor-european-restaurants"
VERSION = "2021-05"


@loader("tripadvisor")
def load(market: Market, version: str | None = None) -> None:
    name = "tripadvisor_eu_restaurants"
    if already_loaded(name, VERSION):
        console.print("tripadvisor already loaded")
        return
    d = bulk_dir("kaggle_tripadvisor")
    zips = list(d.glob("*.zip"))
    if not zips:
        console.print(f"downloading {DATASET} ...")
        subprocess.run(["kaggle", "datasets", "download", "-d", DATASET, "-p", str(d)], check=True)
        zips = list(d.glob("*.zip"))
    zpath = zips[0]
    with zipfile.ZipFile(zpath) as z:
        member = next(n for n in z.namelist() if n.endswith(".csv"))
        z.extract(member, d)
    csv = d / member
    minx, miny, maxx, maxy = bbox(market)
    con = duck()
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE ta AS
        SELECT * FROM read_csv('{csv}', header=true, all_varchar=true, ignore_errors=true, max_line_size=10000000)
        WHERE (lower(city) = 'berlin' OR lower(province) = 'berlin' OR lower(region) = 'berlin')
           OR (try_cast(longitude AS DOUBLE) BETWEEN {minx} AND {maxx}
               AND try_cast(latitude AS DOUBLE) BETWEEN {miny} AND {maxy})
    """)
    n = con.execute("SELECT count(*) FROM ta").fetchone()[0]
    tbl = f"raw.ds_{name}_2021_05"
    con.execute(f'DROP TABLE IF EXISTS pg.raw."ds_{name}_2021_05"')
    con.execute(f'CREATE TABLE pg.raw."ds_{name}_2021_05" AS SELECT * FROM ta')
    console.print(f"{n:,} Berlin TripAdvisor restaurants -> {tbl}")
    register(name, VERSION, f"https://www.kaggle.com/datasets/{DATASET}", tbl,
             "Kaggle dataset licence (see dataset page); research use", release_date=date(2021, 5, 18),
             checksum=sha256_file(zpath), local_path=str(zpath), refresh_cadence="static")
