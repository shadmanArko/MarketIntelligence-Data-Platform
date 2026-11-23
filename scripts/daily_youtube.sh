#!/usr/bin/env bash
# Daily: spend YouTube's free search quota (~90 searches, resets at midnight Pacific = 09:00 Berlin) and read
# whatever videos / channels / comments those searches lead to. Weekly statistics snapshots run in weekly_refresh.sh.
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if grep -q '^MIP_COLLECTOR_DSN=.' .env 2>/dev/null; then
  echo "YouTube searches run daily on the VPS collector; nothing to do here."; exit 0
fi
# The platform database lives on the homelab server (since M4.9) and is reached through the persistent ssh tunnel on
# 127.0.0.1:15434 (launchd agent com.dhakakacchi.homelab-tunnel). The Mac's own mip-postgres is retired: never start it.
# dbt reads its connection from MIP_PG_* (dbt/profiles.yml); `uv run` does not load .env, so load just those names here.
while IFS= read -r line; do export "${line%%=*}=${line#*=}"; done < <(grep -E '^MIP_PG_(HOST|PORT|USER|DB|PASSWORD)=' .env 2>/dev/null)  # split at the FIRST '=' only
mip_db_check() { # the tunnel answers and the database behind it is called mip; prints no credentials
  uv run python - <<'PY'
import os, sys
import psycopg
try:
    with psycopg.connect(host=os.environ["MIP_PG_HOST"], port=int(os.environ["MIP_PG_PORT"]), user=os.environ["MIP_PG_USER"],
                         password=os.environ["MIP_PG_PASSWORD"], dbname=os.environ["MIP_PG_DB"], connect_timeout=8) as c:
        db = c.execute("select current_database()").fetchone()[0]
except KeyError as e:
    sys.exit(f"MIP_PG_{e.args[0].removeprefix('MIP_PG_')} is not set in .env")
except Exception as e:
    sys.exit(f"cannot reach the server's mip database through the tunnel ({type(e).__name__})")
sys.exit(0 if db == "mip" else f"the database behind the tunnel is '{db}', not 'mip'")
PY
}
mip_ready=0
for _ in 1 2 3 4 5 6 7 8 9 10; do mip_db_check 2>"${TMPDIR:-/tmp}/.mip_db_check.$$" && { mip_ready=1; break; }; sleep 9; done
if [ "$mip_ready" != 1 ]; then
  echo "!! preflight FAILED: $(cat "${TMPDIR:-/tmp}/.mip_db_check.$$" 2>/dev/null | tail -1) -- restart the tunnel: launchctl kickstart -k gui/$(id -u)/com.dhakakacchi.homelab-tunnel"
  rm -f "${TMPDIR:-/tmp}/.mip_db_check.$$"; exit 1
fi
rm -f "${TMPDIR:-/tmp}/.mip_db_check.$$"
uv run mip discover -m berlin-food -s youtube
uv run mip fetch -m berlin-food -s youtube -w 2
