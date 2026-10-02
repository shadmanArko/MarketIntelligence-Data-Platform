"""Gate 0: a test connector writes raw rows end to end; retries never duplicate."""

from mip.config import load_market
from mip.core import runner
from mip.db import connect
from tests.conftest import requires_db


def _cleanup(c):
    c.execute("DELETE FROM raw.observations WHERE source='selftest'")
    c.execute("DELETE FROM ops.quarantine WHERE source='selftest'")
    c.execute("DELETE FROM ops.tasks WHERE source='selftest'")


@requires_db
def test_selftest_end_to_end():
    m = load_market("berlin-food")
    with connect() as c:
        _cleanup(c)
    runner.discover(m, "selftest", limit=3)
    first = runner.fetch(m, "selftest", workers=2, skip_health=True)
    again = runner.fetch(m, "selftest", workers=2, skip_health=True)
    with connect() as c:
        n = c.execute("SELECT count(*) n FROM raw.observations WHERE source='selftest'").fetchone()["n"]
        q = c.execute("SELECT count(*) n FROM ops.quarantine WHERE source='selftest'").fetchone()["n"]
        t = c.execute("SELECT count(*) n FROM ops.tasks WHERE source='selftest' AND status='done'").fetchone()["n"]
        _cleanup(c)
    assert first["tasks"]["done"] == 12          # 3 grid points + 9 venues
    assert n == 3 + 6 and q == 3                 # one venue per point violates its contract
    assert t == 12
    assert again["raw"].get("stored", 0) == 0    # rerun is a no-op


@requires_db
def test_schema_drift_recorded_for_new_fields():
    from uuid import uuid4

    from mip.core.raw_store import RawWriter
    from mip.core.runs import start_run
    from mip.core.types import RawRecord

    run_id = start_run("berlin-food", "selftest", "test", {})
    with connect(autocommit=False) as c:
        w = RawWriter(c, "berlin-food", "selftest", "0", run_id, {})
        et = f"drift_{uuid4().hex[:8]}"
        w.write_many([RawRecord(et, "a", {"x": 1}, {})])           # baseline run: no drift
        w2 = RawWriter(c, "berlin-food", "selftest", "0", run_id, {})
        w2.write_many([RawRecord(et, "b", {"x": 1, "y": {"z": 2}}, {})])
        drift = c.execute("SELECT field_path FROM ops.schema_drift WHERE entity_type=%s ORDER BY 1", (et,)).fetchall()
        c.rollback()
    assert [d["field_path"] for d in drift] == ["y", "y.z"]
