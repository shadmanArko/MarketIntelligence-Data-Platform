"""Run records: what ran, which code and config, what it fetched and what failed."""

import subprocess
from typing import Any
from uuid import UUID

from mip.config import market_config_hash
from mip.db import connect
from mip.settings import ROOT


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             timeout=5)
        sha = out.stdout.strip() or None
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=5)
        return f"{sha}-dirty" if sha and dirty.stdout.strip() else sha
    except Exception:
        return None


def start_run(market_id: str, source: str, command: str, args: dict[str, Any]) -> UUID:
    with connect() as c:
        row = c.execute(
            "INSERT INTO ops.runs (market_id, source, command, git_commit, config_hash, args)"
            " VALUES (%s,%s,%s,%s,%s,%s) RETURNING run_id",
            (market_id, source, command, git_commit(), market_config_hash(market_id), args),
        ).fetchone()
        return row["run_id"]


def end_run(run_id: UUID, status: str, metrics: dict[str, Any], error: str | None = None) -> None:
    with connect() as c:
        c.execute(
            "UPDATE ops.runs SET status=%s, ended_at=now(), metrics=%s, error=%s WHERE run_id=%s",
            (status, metrics, error, run_id),
        )


def record_health(source: str, ok: bool, latency_ms: int | None, detail: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO ops.connector_health (source, ok, latency_ms, detail) VALUES (%s,%s,%s,%s)",
            (source, ok, latency_ms, detail[:2000]),
        )
