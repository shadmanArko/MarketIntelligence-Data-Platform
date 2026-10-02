"""Geography reference tables in raw: market boundary, admin areas, H3 cells (res 7/8/9)."""

import json

import h3
import orjson
from rich.console import Console

from mip.config import Market
from mip.db import connect
from mip.geo.areas import areas
from mip.geo.grid import boundary, h3_cells

console = Console()

DDL = """
CREATE TABLE IF NOT EXISTS raw.geo_area (
  market_id text NOT NULL, kind text NOT NULL, code text NOT NULL, name text, osm_id bigint,
  share_in_market double precision, tags jsonb, geom geometry(MultiPolygon, 4326) NOT NULL,
  loaded_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (market_id, kind, code));
CREATE INDEX IF NOT EXISTS geo_area_gist ON raw.geo_area USING gist (geom);
CREATE TABLE IF NOT EXISTS raw.geo_h3 (
  market_id text NOT NULL, cell text NOT NULL, res smallint NOT NULL, lat double precision, lon double precision,
  in_market boolean NOT NULL, PRIMARY KEY (market_id, cell));
"""


def load_grid(market: Market, res: int | None = None) -> None:
    with connect() as c:
        c.execute(DDL)
        c.execute("DELETE FROM raw.geo_area WHERE market_id=%s", (market.id,))
        geom = boundary(market.boundary_path())
        c.execute(
            "INSERT INTO raw.geo_area (market_id, kind, code, name, share_in_market, geom) VALUES "
            "(%s,'market',%s,%s,1, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)))",
            (market.id, market.id, market.geography.city, json.dumps(geom.__geo_interface__)),
        )
        n = 1
        for kind in ("district", "locality", "postcode"):
            for a in areas(market, kind):
                c.execute(
                    "INSERT INTO raw.geo_area (market_id, kind, code, name, osm_id, share_in_market, tags, geom)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s, ST_Multi(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))))"
                    " ON CONFLICT DO NOTHING",
                    (market.id, kind, a["code"], a["name"], a["osm_id"], a["share_in_market"], a["tags"],
                     orjson.dumps(a["geometry"]).decode()),
                )
                n += 1
        c.execute("DELETE FROM raw.geo_h3 WHERE market_id=%s", (market.id,))
        rows = []
        for r in ([res] if res else [7, 8, 9]):
            inside = set(h3_cells(market, r))
            for cell in set(h3_cells(market, r, buffer_rings=2)):
                lat, lon = h3.cell_to_latlng(cell)
                rows.append((market.id, cell, r, lat, lon, cell in inside))
        with c.cursor() as cur:
            cur.executemany("INSERT INTO raw.geo_h3 VALUES (%s,%s,%s,%s,%s,%s)", rows)
    console.print(f"[green]geo loaded:[/] {n} areas, {len(rows):,} H3 cells")
