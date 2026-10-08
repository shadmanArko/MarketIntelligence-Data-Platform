#!/usr/bin/env bash
# Catch-up wrapper for the weekly refresh. launchd runs it on Sundays 01:00, every hour and at login
# (~/Library/LaunchAgents/com.dhakakacchi.mip.weekly.plist). It starts scripts/weekly_refresh.sh only if no refresh
# finished since the last Sunday 01:00 Berlin, never twice at once, and retries a failed attempt after 6 hours.
# So a Sunday with the Mac switched off is made up within an hour of switching it on.
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
mkdir -p data/logs

due=$(/usr/bin/python3 - <<'PY'
import datetime as dt, os, pathlib, zoneinfo
berlin = zoneinfo.ZoneInfo("Europe/Berlin")
now = dt.datetime.now(berlin)
anchor = (now - dt.timedelta(days=now.isoweekday() % 7)).replace(hour=1, minute=0, second=0, microsecond=0)
if anchor > now:
    anchor -= dt.timedelta(days=7)
ok = pathlib.Path("data/logs/weekly_last_success")
att = pathlib.Path("data/logs/weekly_last_attempt")
last_ok = dt.datetime.fromisoformat(ok.read_text().strip().replace("Z", "+00:00")) if ok.exists() else None
last_try = dt.datetime.fromtimestamp(att.stat().st_mtime, berlin) if att.exists() else None
if last_ok and last_ok >= anchor:
    print("no")
elif last_try and last_try >= anchor and now - last_try < dt.timedelta(hours=6):
    print("no")
else:
    print("yes")
PY
)
[ "$due" = "yes" ] || exit 0

LOCK=data/logs/.weekly_lock
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -f "$LOCK/pid" ] && kill -0 "$(cat "$LOCK/pid")" 2>/dev/null; then exit 0; fi   # running
  rm -rf "$LOCK"; mkdir "$LOCK"                                                        # stale lock
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT
touch data/logs/weekly_last_attempt
echo "== $(date -u +%FT%TZ) weekly refresh is due: starting"
caffeinate -is /bin/bash scripts/weekly_refresh.sh
