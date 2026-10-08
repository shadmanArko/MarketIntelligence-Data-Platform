"""Import raw data collected 24/7 on the VPS collector into this (Mac) database.

The VPS runs the same connectors with the same code for the light, official-API sources (YouTube searches, Berlin
events, Wikipedia pageviews, Reddit's recent months). Raw stays immutable and content-addressed, so importing is a
plain copy: runs, then payloads (keyed by sha256), then observations (keyed by their uuid); everything ON CONFLICT
DO NOTHING, so a repeated or overlapping import changes nothing.
"""

from __future__ import annotations

import socket
import subprocess
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from mip.db import connect
from mip.settings import settings

SOURCES = ("youtube", "berlin_events", "wikipedia", "reddit_archive")
BATCH = 2000
OVERLAP = timedelta(hours=2)  # re-read a little before the watermark: late-committed rows are never missed


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


@contextmanager
def tunnel():
    """Open the tunnel-only SSH forward to the collector database (unless something already listens)."""
    port = int(psycopg.conninfo.conninfo_to_dict(settings().mip_collector_dsn).get("port") or 5436)
    if _port_open(port):
        yield
        return
    key = str(Path(settings().mip_collector_ssh_key).expanduser())
    proc = subprocess.Popen(
        [
            "ssh",
            "-i",
            key,
            "-N",
            "-L",
            f"{port}:127.0.0.1:5442",
            "-o",
            "BatchMode=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "ConnectTimeout=15",
            settings().mip_collector_ssh,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(100):
            if _port_open(port):
                break
            if proc.poll() is not None:
                raise RuntimeError(f"collector tunnel failed: {(proc.stderr.read() or '').strip()}")
            time.sleep(0.2)
        else:
            raise RuntimeError("collector tunnel did not come up")
        yield
    finally:
        proc.terminate()


def _columns(c, schema: str, table: str) -> dict[str, str]:
    """column -> data type, in table order (jsonb columns need explicit wrapping; Postgres arrays must not)."""
    return {
        r["column_name"]: r["data_type"]
        for r in c.execute(
            "select column_name, data_type from information_schema.columns where table_schema=%s and table_name=%s "
            "order by ordinal_position",
            (schema, table),
        )
    }


def _copy(src, dst, schema: str, table: str, where: sql.Composable, params: tuple, coltypes: dict[str, str]) -> int:
    cols = list(coltypes)
    rows = src.execute(
        sql.SQL("select {} from {}.{} where ").format(
            sql.SQL(", ").join(map(sql.Identifier, cols)), sql.Identifier(schema), sql.Identifier(table)
        )
        + where,
        params,
    ).fetchall()
    if not rows:
        return 0
    ins = sql.SQL("insert into {}.{} ({}) values ({}) on conflict do nothing").format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, cols)),
        sql.SQL(", ").join(sql.Placeholder() * len(cols)),
    )
    data = [[Jsonb(r[c]) if coltypes[c] == "jsonb" and r[c] is not None else r[c] for c in cols] for r in rows]
    with dst.cursor() as cur:
        cur.executemany(ins, data)
        return cur.rowcount if cur.rowcount >= 0 else len(data)


def import_from_collector(log=print) -> dict:
    if not settings().mip_collector_dsn:
        raise RuntimeError("MIP_COLLECTOR_DSN is not set (see docs/credentials-guide.md, VPS collector)")
    with connect() as mac:
        wm = mac.execute("select max(to_fetched_at) m from ops.collector_import where status='succeeded'").fetchone()[
            "m"
        ]
        imp = mac.execute(
            "insert into ops.collector_import (from_fetched_at) values (%s) returning import_id", (wm,)
        ).fetchone()["import_id"]
        mac.commit()
    since = (wm - OVERLAP) if wm else None
    totals = {"runs": 0, "payloads": 0, "observations": 0}
    last, srcs = since, set()
    try:
        with (
            tunnel(),
            psycopg.connect(settings().mip_collector_dsn, row_factory=dict_row, connect_timeout=15) as vps,
            connect() as mac,
        ):
            vps.read_only = True
            run_cols, pay_cols, obs_cols = (
                _columns(mac, "ops", "runs"),
                _columns(mac, "raw", "payloads"),
                _columns(mac, "raw", "observations"),
            )
            cursor = since
            while True:
                where = sql.SQL("source = any(%s)") + (sql.SQL(" and fetched_at > %s") if cursor else sql.SQL(""))
                params = (list(SOURCES), cursor) if cursor else (list(SOURCES),)
                batch = vps.execute(
                    sql.SQL(
                        "select observation_id, fetched_at, run_id, payload_sha256, source from raw.observations where "
                    )
                    + where
                    + sql.SQL(" order by fetched_at, observation_id limit %s"),
                    (*params, BATCH),
                ).fetchall()
                if not batch:
                    break
                lo, hi = batch[0]["fetched_at"], batch[-1]["fetched_at"]
                for month in {(b["fetched_at"].year, b["fetched_at"].month) for b in batch}:
                    mac.execute(
                        "select ops.ensure_month_partition('raw.observations'::regclass, make_date(%s, %s, 1))", month
                    )
                run_ids = list({b["run_id"] for b in batch})
                shas = list({bytes(b["payload_sha256"]) for b in batch})
                totals["runs"] += _copy(vps, mac, "ops", "runs", sql.SQL("run_id = any(%s)"), (run_ids,), run_cols)
                totals["payloads"] += _copy(
                    vps, mac, "raw", "payloads", sql.SQL("payload_sha256 = any(%s)"), (shas,), pay_cols
                )
                ids = [b["observation_id"] for b in batch]
                totals["observations"] += _copy(
                    vps,
                    mac,
                    "raw",
                    "observations",
                    sql.SQL("observation_id = any(%s) and fetched_at between %s and %s"),
                    (ids, lo, hi),
                    obs_cols,
                )
                mac.commit()
                srcs |= {b["source"] for b in batch}
                last = cursor = hi
                log(f"  imported up to {hi:%Y-%m-%d %H:%M}: {totals}")
                if len(batch) < BATCH:
                    break
        with connect() as mac:
            mac.execute(
                """update ops.collector_import set ended_at=now(), status='succeeded', to_fetched_at=%s,
                           runs=%s, payloads=%s, observations=%s, sources=%s where import_id=%s""",
                (last or wm, totals["runs"], totals["payloads"], totals["observations"], sorted(srcs), imp),
            )
    except Exception as e:
        with connect() as mac:
            mac.execute(
                "update ops.collector_import set ended_at=now(), status='failed', error=%s where import_id=%s",
                (f"{type(e).__name__}: {e}"[:500], imp),
            )
        raise
    return {**totals, "sources": sorted(srcs), "until": str(last)}
