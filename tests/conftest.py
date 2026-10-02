import os

import pytest

from mip.db import connect


def _db_ok() -> bool:
    try:
        with connect() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _db_ok() and not os.getenv("CI"), reason="Postgres not running")
