"""A fetch whose workers lose their database connection must end 'failed', never 'succeeded' (22 Nov 2026).

No database needed: the runner's DB touch points are replaced with fakes, and the worker connection raises the same
psycopg.OperationalError the ssh-tunnel reload produced.
"""

import psycopg
import pytest
from typer.testing import CliRunner

from mip.config import load_market
from mip.core import runner


class _Result:
    def __init__(self, rows=None, one=None):
        self._rows, self._one = rows or [], one

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one


class _Conn:
    """Fake psycopg connection: setup queries answer, the worker connection can be made to drop."""

    def __init__(self, lost: bool = False):
        self.lost = lost

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if "count(*)" in sql:
            return _Result(one={"n": 3})
        return _Result(rows=[])

    def commit(self):
        if self.lost:
            raise psycopg.OperationalError("the connection is lost")

    def rollback(self):
        if self.lost:
            raise psycopg.OperationalError("the connection is lost")


class _Writer:
    def __init__(self, *a, **k):
        self.stats = {"stored": 0}

    def write_many(self, records, task_id):
        pass


class _Connector:
    version = "0"
    contracts: dict = {}
    rate_limit = None

    def fetch(self, ref):
        return iter(())


@pytest.fixture
def fake_runtime(monkeypatch):
    runs: dict = {}
    state = {"lost": False, "claims": 0}

    def connect(autocommit=True):
        return _Conn(lost=state["lost"] and not autocommit)  # only the workers' own connections drop

    def claim(c, market_id, source, worker, run_id, n, entity_types):
        state["claims"] += 1
        if state["claims"] > 6:
            return []
        return [{"task_id": state["claims"], "entity_type": "venue", "natural_key": str(state["claims"]),
                 "params": {}, "priority": 0, "attempts": 0}]

    monkeypatch.setattr(runner, "connect", connect)
    monkeypatch.setattr(runner, "release_orphans", lambda m, s: 0)
    monkeypatch.setattr(runner, "start_run", lambda *a, **k: "run-1")
    monkeypatch.setattr(runner, "end_run", lambda run_id, status, metrics, err=None: runs.update(
        status=status, metrics=metrics, err=err))
    monkeypatch.setattr(runner, "make_connector", lambda m, s: _Connector())
    monkeypatch.setattr(runner, "RawWriter", _Writer)
    monkeypatch.setattr(runner.queue, "claim", claim)
    monkeypatch.setattr(runner.queue, "complete", lambda c, t: None)
    monkeypatch.setattr(runner.queue, "fail", lambda *a, **k: None)
    monkeypatch.setattr(runner, "backoff_delay", lambda *a, **k: 1)
    return runs, state


def test_fetch_succeeds_when_connections_hold(fake_runtime):
    runs, state = fake_runtime
    res = runner.fetch(load_market("berlin-food"), "wolt", workers=2, skip_health=True)
    assert res["status"] == "succeeded" and runs["status"] == "succeeded"
    assert res["tasks"]["done"] == 6


def test_lost_db_connection_marks_run_failed(fake_runtime):
    runs, state = fake_runtime
    state["lost"] = True
    res = runner.fetch(load_market("berlin-food"), "wolt", workers=2, skip_health=True)
    assert res["status"] == "failed"
    assert runs["status"] == "failed"
    assert "connection is lost" in runs["err"] and "2/2 worker(s) died" in runs["err"]


def test_cli_fetch_exits_nonzero_on_failed_run(fake_runtime):
    from mip.cli import app

    _, state = fake_runtime
    state["lost"] = True
    out = CliRunner().invoke(app, ["fetch", "-m", "berlin-food", "-s", "wolt", "-w", "1", "--skip-health"])
    assert out.exit_code == 1
