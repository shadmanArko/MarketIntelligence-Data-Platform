"""VPS collector -> Mac import: copies runs, payloads, observations; idempotent; only collector sources.

Needs MIP_TEST_ADMIN_DSN (a Postgres 18 where the user may CREATE DATABASE, e.g. the local mip container)."""

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql

ADMIN = os.environ.get("MIP_TEST_ADMIN_DSN")
pytestmark = pytest.mark.skipif(not ADMIN, reason="MIP_TEST_ADMIN_DSN not set")


@pytest.fixture
def two_dbs(monkeypatch):
    names = [f"mip_t_{uuid.uuid4().hex[:8]}" for _ in range(2)]
    with psycopg.connect(ADMIN, autocommit=True) as c:
        for n in names:
            c.execute(sql.SQL("create database {}").format(sql.Identifier(n)))
    dsns = [psycopg.conninfo.make_conninfo(ADMIN, dbname=n) for n in names]
    for d in dsns:  # same as deploy/collector/initdb: the reader-role migration grants on these schemas
        with psycopg.connect(d, autocommit=True) as c:
            c.execute(
                "create schema if not exists core; create schema if not exists marts; "
                "create schema if not exists ml; create schema if not exists staging"
            )
    from mip import db
    from mip.settings import settings

    cfg = settings()
    for d in dsns:
        monkeypatch.setattr(cfg, "mip_database_url", d)
        db.migrate()
    monkeypatch.setattr(cfg, "mip_database_url", dsns[1])  # the "Mac"
    monkeypatch.setattr(cfg, "mip_collector_dsn", dsns[0])  # the "VPS collector" (port already open)
    yield dsns
    with psycopg.connect(ADMIN, autocommit=True) as c:
        for n in names:
            c.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(n)))


def seed(dsn, source, n, start):
    with psycopg.connect(dsn) as c:
        run = c.execute(
            "insert into ops.runs (market_id, source, command) values ('berlin-food', %s, 'fetch') returning run_id",
            (source,),
        ).fetchone()[0]
        for i in range(n):
            body = {"i": i, "source": source}
            sha = hashlib.sha256(json.dumps(body).encode()).digest()
            c.execute(
                "insert into raw.payloads (payload_sha256, payload, byte_size) values (%s, %s, 10) "
                "on conflict do nothing",
                (sha, json.dumps(body)),
            )
            at = start + timedelta(minutes=i)
            c.execute(
                "select ops.ensure_month_partition('raw.observations'::regclass, %s)", (at.date().replace(day=1),)
            )
            c.execute(
                """insert into raw.observations (market_id, source, entity_type, natural_key, run_id,
                         connector_ver, request_meta, http_status, payload_sha256, fetched_at)
                         values ('berlin-food', %s, 'feed', %s, %s, '1.0', '{}', 200, %s, %s)""",
                (source, f"k{i}", run, sha, at),
            )


def count(dsn, q):
    with psycopg.connect(dsn) as c:
        return c.execute(q).fetchone()[0]


def test_import_is_complete_idempotent_and_filtered(two_dbs):
    from mip.collector import import_from_collector

    vps, mac = two_dbs
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    seed(vps, "berlin_events", 5, t0)
    seed(vps, "wolt", 3, t0)  # not a collector source: must not be imported
    r = import_from_collector(log=lambda *_: None)
    assert r["observations"] == 5 and r["sources"] == ["berlin_events"]
    assert count(mac, "select count(*) from raw.observations") == 5
    assert count(mac, "select count(*) from raw.payloads") == 5
    again = import_from_collector(log=lambda *_: None)  # nothing new, overlap window re-read: no duplicates
    assert again["observations"] == 0 and count(mac, "select count(*) from raw.observations") == 5
    seed(vps, "youtube", 2, t0 + timedelta(days=3))  # new data later
    assert import_from_collector(log=lambda *_: None)["observations"] == 2
    assert count(mac, "select count(*) from ops.collector_import where status='succeeded'") == 3
