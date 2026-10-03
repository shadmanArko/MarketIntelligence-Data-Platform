"""Bulk datasets: download once, keep the file unchanged, load into a versioned raw.ds_* table, register."""

import hashlib
from collections.abc import Callable
from pathlib import Path

import duckdb
from rich.console import Console

from mip.config import Market
from mip.db import connect
from mip.settings import settings

console = Console(stderr=True)
LOADERS: dict[str, Callable] = {}


def loader(name: str):
    def deco(fn):
        LOADERS[name] = fn
        return fn

    return deco


def bulk_dir(name: str) -> Path:
    p = settings().data_dir / "bulk" / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def table_name(name: str, version: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in version.lower()).strip("_")
    return f"raw.ds_{name}_{safe}"


def duck() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for ext in ("httpfs", "spatial", "postgres"):
        con.execute(f"INSTALL {ext}; LOAD {ext};")
    url = settings().mip_database_url
    con.execute(f"ATTACH '{url}' AS pg (TYPE postgres)")
    return con


SCALAR = ("VARCHAR", "DOUBLE", "FLOAT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT", "BOOLEAN", "DATE",
          "TIMESTAMP", "DECIMAL", "UBIGINT", "UINTEGER", "HUGEINT")


def portable_select(con: duckdb.DuckDBPyConnection, relation_sql: str, geometry_cols: tuple[str, ...] = ("geometry",)) -> str:
    """SELECT list that keeps every column: scalars as-is, nested types as JSON text, geometry as WKT + centroid."""
    cols = con.execute(f"DESCRIBE SELECT * FROM {relation_sql} LIMIT 0").fetchall()
    out = []
    for name, typ, *_ in cols:
        q = f'"{name}"'
        if name in geometry_cols or typ.startswith("GEOMETRY"):
            out += [f"ST_AsText({q}) AS {name}_wkt", f"ST_Y(ST_Centroid({q})) AS lat", f"ST_X(ST_Centroid({q})) AS lon"]
        elif typ.split("(")[0] in SCALAR:
            out.append(q)
        else:
            out.append(f"to_json({q})::VARCHAR AS {q}")
    return ", ".join(out)


def already_loaded(name: str, version: str) -> bool:
    with connect() as c:
        return c.execute("SELECT 1 FROM ops.datasets WHERE name=%s AND version=%s", (name, version)).fetchone() is not None


def register(name: str, version: str, source_url: str, raw_table: str, terms: str, *, release_date=None,
             checksum: str | None = None, local_path: str | None = None, refresh_cadence: str | None = None,
             meta: dict | None = None) -> int:
    with connect() as c:
        schema, tbl = raw_table.split(".")
        n = c.execute(f'SELECT count(*) n FROM {schema}."{tbl}"').fetchone()["n"]
        c.execute(
            "INSERT INTO ops.datasets (name, version, source_url, release_date, checksum, terms, row_count, raw_table,"
            " local_path, refresh_cadence, meta) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (name, version) DO UPDATE SET row_count=EXCLUDED.row_count, checksum=EXCLUDED.checksum,"
            " loaded_at=now(), meta=EXCLUDED.meta",
            (name, version, source_url, release_date, checksum, terms, n, raw_table, local_path, refresh_cadence,
             meta or {}),
        )
    console.print(f"[green]registered {name} {version}[/]: {n:,} rows -> {raw_table}")
    return n


def load_dataset(name: str, market: Market, version: str | None = None) -> None:
    from mip.datasets import (  # noqa: F401  (register loaders)
        afs_population,
        berlin_open,
        calendar,
        crux,
        foursquare,
        kaggle_tripadvisor,
        occasions,
        osm,
        overture,
        wikidata_dishes,
        zensus,
    )

    if name == "all":
        for n in ("osm", "overture", "zensus", "holidays", "weather", "crux", "lor", "tripadvisor"):
            try:
                LOADERS[n](market, version)
            except Exception as e:
                console.print(f"[red]{n} failed:[/] {type(e).__name__}: {e}")
        return
    if name not in LOADERS:
        raise SystemExit(f"unknown dataset {name!r}; known: {sorted(LOADERS)}")
    LOADERS[name](market, version)
