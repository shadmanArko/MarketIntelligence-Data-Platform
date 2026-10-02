"""Zensus 2022 grid data (100 m cells, EPSG:3035), clipped to the market and loaded per variable.

Each ZIP holds national CSVs at 100 m / 1 km / 10 km; the finest available grid is kept. dbt aggregates
cells to H3 res 8 in core.area_stat (population-weighted for shares, means and rents).
"""


import zipfile

import duckdb
import httpx

from mip.config import Market
from mip.datasets import already_loaded, bulk_dir, console, duck, loader, register, sha256_file
from mip.geo.grid import bbox

BASE = "https://www.destatis.de/static/DE/zensus/gitterdaten/"
VARIABLES = {
    "population": "Zensus2022_Bevoelkerungszahl.zip",
    "foreigner_share": "Auslaenderanteil_in_Gitterzellen.zip",
    "foreigner_share_eu": "Auslaenderanteil_EU_nichtEU_Gitterzellen.zip",
    "nationality_groups": "Zensus2022_Staatsangehoerigkeit_Gruppen_in_Gitterzellen.zip",
    "nationality_countries": "Staatsangehoerigkeit_nach_ausgewaehlten_Laendern.zip",
    "birth_country_groups": "Zensus2022_Geburtsland_Gruppen_in_Gitterzellen.zip",
    "mean_age": "Durchschnittsalter_in_Gitterzellen.zip",
    "age_10y": "Alter_in_10er-Jahresgruppen.zip",
    "share_under_18": "Anteil_unter_18-jaehrige_in_Gitterzellen.zip",
    "share_65_plus": "Anteil_ab_65-jaehrige_in_Gitterzellen.zip",
    "household_size_mean": "Durchschnittliche_Haushaltsgroesse_in_Gitterzellen.zip",
    "household_size": "Zensus2022_Groesse_des_privaten_Haushalts_in_Gitterzellen.zip",
    "household_type": "Typ_des_privaten_Haushalts_Lebensform.zip",
    "rent_net_cold": "Zensus2022_Durchschn_Nettokaltmiete.zip",
    "living_space_per_person": "Durchschnittliche_Wohnflaeche_je_Bewohner_in_Gitterzellen.zip",
    "owner_rate": "Eigentuemerquote_in_Gitterzellen.zip",
    "vacancy_rate": "Leerstandsquote_in_Gitterzellen.zip",
    "religion": "Religion.zip",
}
VERSION = "2022"


def _pick_csv(z: zipfile.ZipFile) -> str:
    names = [n for n in z.namelist() if n.lower().endswith(".csv")]
    for grid in ("100m", "100 m", "1km", "10km"):
        hits = [n for n in names if grid in n.replace("-", "").lower().replace("gitter", "")]
        if hits:
            return sorted(hits, key=len)[0]
    if not names:
        raise ValueError("no CSV in archive")
    return names[0]


def _load_one(con: duckdb.DuckDBPyConnection, var: str, fname: str, market: Market) -> None:
    name = f"zensus2022_{var}"
    if already_loaded(name, VERSION):
        console.print(f"{name} already loaded")
        return
    path = bulk_dir("zensus") / fname
    if not path.exists():
        console.print(f"downloading {fname} ...")
        with httpx.stream("GET", BASE + fname, follow_redirects=True, timeout=900,
                          headers={"User-Agent": "mip/0.1"}) as r, path.open("wb") as f:
            r.raise_for_status()
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    with zipfile.ZipFile(path) as z:
        member = _pick_csv(z)
        raw = z.read(member)
    text = raw.decode("utf-8-sig", errors="replace") if raw[:3] == b"\xef\xbb\xbf" else raw.decode("latin-1")
    csv_path = bulk_dir("zensus") / f"{var}.csv"
    csv_path.write_text(text)
    minx, miny, maxx, maxy = bbox(market)
    con.execute(f"CREATE OR REPLACE TEMP TABLE z AS SELECT * FROM read_csv('{csv_path}', delim=';', header=true,"
                " all_varchar=true, ignore_errors=true)")
    cols = [c[0] for c in con.execute("DESCRIBE z").fetchall()]
    xcol = next(c for c in cols if c.lower().startswith("x_mp"))
    ycol = next(c for c in cols if c.lower().startswith("y_mp"))
    idcol = next(c for c in cols if c.lower().startswith("gitter_id"))
    cell_m = 100 if "100m" in idcol.lower() else 1000 if "1km" in idcol.lower() else 10000
    values = [c for c in cols if c not in (xcol, ycol, idcol)]
    # numbers use German decimal commas; '–' and '' mean suppressed / no value -> NULL
    val_sql = ", ".join(
        f"try_cast(replace(nullif(nullif(trim(\"{c}\"), '–'), ''), ',', '.') AS DOUBLE) AS \"{c.lower()}\"" for c in values)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE zb AS
        WITH p AS (
          SELECT "{idcol}" AS grid_id, CAST("{xcol}" AS DOUBLE) AS x, CAST("{ycol}" AS DOUBLE) AS y, {val_sql} FROM z),
        g AS (SELECT *, ST_Transform(ST_Point(x, y), 'EPSG:3035', 'EPSG:4326', always_xy := true) AS pt FROM p)
        SELECT grid_id, {cell_m} AS cell_m, ST_Y(pt) AS lat, ST_X(pt) AS lon, * EXCLUDE (grid_id, x, y, pt)
        FROM g WHERE ST_X(pt) BETWEEN {minx} AND {maxx} AND ST_Y(pt) BETWEEN {miny} AND {maxy}
    """)
    n = con.execute("SELECT count(*) FROM zb").fetchone()[0]
    tbl = f"raw.ds_{name}"
    con.execute(f'DROP TABLE IF EXISTS pg.raw."ds_{name}"')
    con.execute(f'CREATE TABLE pg.raw."ds_{name}" AS SELECT * FROM zb')
    register(name, VERSION, BASE + fname, tbl, "Datenlizenz Deutschland Namensnennung 2.0 (Zensus 2022, Destatis)",
             checksum=sha256_file(path), local_path=str(path), refresh_cadence="decennial",
             meta={"csv_member": member, "cell_m": cell_m, "value_columns": [v.lower() for v in values], "rows": n})


@loader("zensus")
def load(market: Market, version: str | None = None) -> None:
    con = duck()
    for var, fname in VARIABLES.items():
        try:
            _load_one(con, var, fname, market)
        except Exception as e:
            console.print(f"[red]zensus {var} failed:[/] {type(e).__name__}: {e}")


