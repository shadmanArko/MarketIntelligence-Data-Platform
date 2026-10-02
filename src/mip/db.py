"""Postgres connections and the migration runner (migrations own raw and ops)."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

import orjson
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb, JsonbDumper, set_json_dumps, set_json_loads
from psycopg_pool import ConnectionPool

from mip.settings import ROOT, settings

MIGRATIONS_DIR = ROOT / "db" / "migrations"


def _dumps(obj) -> str:
    return orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS).decode()


set_json_dumps(_dumps)
set_json_loads(orjson.loads)
psycopg.adapters.register_dumper(dict, JsonbDumper)  # dicts are always JSONB; lists stay Postgres arrays

__all__ = ["Jsonb", "conn", "connect", "migrate", "pool"]


@lru_cache
def pool() -> ConnectionPool:
    p = ConnectionPool(
        settings().mip_database_url,
        min_size=1,
        max_size=16,
        kwargs={"row_factory": dict_row, "autocommit": False},
        open=True,
    )
    return p


@contextmanager
def conn() -> Iterator[psycopg.Connection]:
    with pool().connection() as c:
        yield c


def connect(autocommit: bool = True) -> psycopg.Connection:
    return psycopg.connect(settings().mip_database_url, row_factory=dict_row, autocommit=autocommit)


def migrate() -> list[str]:
    applied: list[str] = []
    with connect() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations ("
            " name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r["name"]: r["checksum"] for r in c.execute("SELECT name, checksum FROM public.schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            sql = path.read_text()
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            if path.name in done:
                if done[path.name] != checksum:
                    raise RuntimeError(f"migration {path.name} changed after being applied; add a new one")
                continue
            with c.transaction():
                c.execute(sql)
                c.execute(
                    "INSERT INTO public.schema_migrations (name, checksum) VALUES (%s, %s)", (path.name, checksum)
                )
            applied.append(path.name)
    return applied
