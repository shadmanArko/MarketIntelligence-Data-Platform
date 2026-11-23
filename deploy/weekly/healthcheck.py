"""Container health check for the weekly job: the mip database answers. Prints no credentials.

Unhealthy while the job runs = the job has lost its database (the failure mode of 22 Nov 2026); the run itself
then fails and the systemd unit retries. Reads the password file directly: health checks do not get the
entrypoint's environment.
"""

import os
import sys
from pathlib import Path

import psycopg

try:
    pw = Path("/run/secrets/mip_pg_password").read_text().strip()
    with psycopg.connect(host=os.environ["MIP_PG_HOST"], port=int(os.environ["MIP_PG_PORT"]),
                         user=os.environ["MIP_PG_USER"], password=pw, dbname=os.environ["MIP_PG_DB"],
                         connect_timeout=10) as c:
        db = c.execute("select current_database()").fetchone()[0]
except Exception as e:  # noqa: BLE001
    sys.exit(f"unhealthy: {type(e).__name__}")
sys.exit(0 if db == "mip" else f"unhealthy: connected to '{db}', not 'mip'")
