"""Resumable work queue in Postgres: one row per unit of work, claimed with SKIP LOCKED."""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

import psycopg

from mip.core.types import EntityRef

STALE_CLAIM = "30 minutes"


def task_key(market_id: str, source: str, ref: EntityRef) -> str:
    return f"{market_id}|{source}|{ref.entity_type}|{ref.natural_key}"


def enqueue(
    c: psycopg.Connection,
    market_id: str,
    source: str,
    refs: Iterable[EntityRef],
    parent_task_id: UUID | None = None,
    refresh: bool = False,
) -> int:
    """Insert tasks; existing keys are left alone unless refresh=True (then done tasks go back to pending)."""
    rows = [
        (task_key(market_id, source, r), market_id, source, r.entity_type, r.natural_key, r.params, r.priority,
         parent_task_id)
        for r in refs
    ]
    if not rows:
        return 0
    conflict = (
        "ON CONFLICT (task_key) DO UPDATE SET status='pending', attempts=0, next_attempt_at=now(),"
        " params=EXCLUDED.params, updated_at=now() WHERE ops.tasks.status IN ('done','dead')"
        if refresh
        else "ON CONFLICT (task_key) DO NOTHING"
    )
    n = 0
    with c.cursor() as cur:
        for i in range(0, len(rows), 1000):
            chunk = rows[i : i + 1000]
            cur.executemany(
                "INSERT INTO ops.tasks (task_key, market_id, source, entity_type, natural_key, params, priority,"
                f" parent_task_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) {conflict}",
                chunk,
            )
            n += cur.rowcount if cur.rowcount > 0 else 0
    return n


def claim(c: psycopg.Connection, market_id: str, source: str, worker: str, run_id: UUID, n: int = 1,
          entity_types: list[str] | None = None) -> list[dict[str, Any]]:
    et_filter = "AND entity_type = ANY(%(ets)s)" if entity_types else ""
    return c.execute(
        f"""
        UPDATE ops.tasks t SET status='running', claimed_by=%(w)s, claimed_at=now(), attempts=t.attempts+1,
               last_run_id=%(run)s, updated_at=now()
        WHERE task_id IN (
          SELECT task_id FROM ops.tasks
          WHERE market_id=%(m)s AND source=%(s)s {et_filter}
            AND ((status IN ('pending','failed') AND next_attempt_at <= now())
                 OR (status='running' AND claimed_at < now() - interval '{STALE_CLAIM}'))
          ORDER BY priority, md5(task_key)  -- scatter: parallel workers spread over hosts / cells
          LIMIT %(n)s
          FOR UPDATE SKIP LOCKED)
        RETURNING task_id, entity_type, natural_key, params, attempts, max_attempts, priority
        """,
        {"w": worker, "run": run_id, "m": market_id, "s": source, "n": n, "ets": entity_types},
    ).fetchall()


def complete(c: psycopg.Connection, task_id: UUID) -> None:
    c.execute(
        "UPDATE ops.tasks SET status='done', last_error=NULL, updated_at=now() WHERE task_id=%s", (task_id,)
    )


def fail(c: psycopg.Connection, task_id: UUID, error: str, delay_s: float, dead: bool = False) -> None:
    c.execute(
        "UPDATE ops.tasks SET status=CASE WHEN %s OR attempts >= max_attempts THEN 'dead' ELSE 'failed' END,"
        " last_error=%s, next_attempt_at=now() + make_interval(secs => %s), updated_at=now() WHERE task_id=%s",
        (dead, error[:2000], delay_s, task_id),
    )


def defer(c: psycopg.Connection, task_id: UUID, reason: str, delay_s: float) -> None:
    """Back to pending, attempt not counted, not claimable before the delay has passed."""
    c.execute(
        "UPDATE ops.tasks SET status='pending', attempts=greatest(attempts-1,0), last_error=%s,"
        " next_attempt_at=now() + make_interval(secs => %s), updated_at=now() WHERE task_id=%s",
        (reason[:2000], delay_s, task_id),
    )


def release(c: psycopg.Connection, task_id: UUID) -> None:
    """Give a claimed task back untouched (e.g. breaker opened before we started)."""
    c.execute(
        "UPDATE ops.tasks SET status='pending', attempts=greatest(attempts-1,0), updated_at=now() WHERE task_id=%s",
        (task_id,),
    )


def summary(c: psycopg.Connection, market_id: str, source: str | None = None) -> list[dict[str, Any]]:
    return c.execute(
        "SELECT source, entity_type, status, count(*) AS n FROM ops.tasks WHERE market_id=%s"
        " AND (%s::text IS NULL OR source=%s) GROUP BY 1,2,3 ORDER BY 1,2,3",
        (market_id, source, source),
    ).fetchall()
