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
