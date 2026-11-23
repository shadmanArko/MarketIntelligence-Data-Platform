#!/usr/bin/env bash
# Weekly snapshot: re-observe every delivery listing, fee, menu price and new review, plus first-party data and
# Wikipedia interest, Reddit / YouTube / Berlin events, then rebuild, test, report and export a new training-set version. Every run adds new
# timestamped observations (raw is append-only), which is what turns the platform into a time series.
# Mac: scheduled by ~/Library/LaunchAgents/com.dhakakacchi.mip.weekly.plist via scripts/weekly_if_due.sh (Sundays 01:00).
# Server: run inside the deploy/weekly container by the mip-weekly systemd timer. Safe to run by hand.
#
# Exit status and markers (read by scripts/weekly_if_due.sh and the systemd unit):
#   0 = every step succeeded -> writes $LOGS/weekly_last_success (the catch-up stops retrying this week)
#   1 = a step failed        -> no success marker, so the catch-up retries; the failed steps are listed at the end
# $LOGS/weekly_last_status is written either way. `mip report` exiting 3 (data-quality checks failed) is a WARNING:
# it is listed and counted, but does not fail the week; a report crash (any other exit code) does.
#
# Overridable for the container and for tests: MIP_CMD, DBT_CMD, PY_CMD (commands), MIP_LOG_DIR, MIP_ENV_FILE,
# MIP_MARKET, MIP_PREFLIGHT_TRIES, MIP_METRICS_DIR (node-exporter textfile directory, optional).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
M="${MIP_MARKET:-berlin-food}"
LOGS="${MIP_LOG_DIR:-data/logs}"
ENV_FILE="${MIP_ENV_FILE:-.env}"
read -r -a MIP_ARR <<< "${MIP_CMD:-uv run mip}"
read -r -a DBT_ARR <<< "${DBT_CMD:-uv run dbt}"
read -r -a PY_ARR <<< "${PY_CMD:-uv run python}"
L="$LOGS/weekly_$(date +%Y%m%d)"
mkdir -p "$L"
STARTED="$(date -u +%FT%TZ)"

FAILED_N=0; FAILED_LIST=""; WARN_N=0; WARN_LIST=""
fail() { FAILED_N=$((FAILED_N + 1)); FAILED_LIST="${FAILED_LIST}  - $*"$'\n'; echo "!! failed: $*"; }
warn() { WARN_N=$((WARN_N + 1)); WARN_LIST="${WARN_LIST}  - $*"$'\n'; echo "!! warning: $*"; }
run() { echo "== $(date -u +%F' '%H:%M) $*"; "$@"; local rc=$?; [ "$rc" -eq 0 ] || fail "$* (exit $rc)"; return "$rc"; }
mip() { command "${MIP_ARR[@]}" "$@"; }   # `command`: MIP_CMD=mip must not call this function again
# shellcheck disable=SC2329  # called through run()
dbt() { command "${DBT_ARR[@]}" "$@"; }

finish() {  # status file + optional metrics + success marker only when nothing failed
  local result=ok; [ "$FAILED_N" -eq 0 ] || result=failed
  {
    echo "result=$result"
    echo "started_at=$STARTED"
    echo "finished_at=$(date -u +%FT%TZ)"
    echo "failed_steps=$FAILED_N"
    echo "warnings=$WARN_N"
    echo "log_dir=$L"
  } > "$LOGS/weekly_last_status"
  if [ -n "${MIP_METRICS_DIR:-}" ] && [ -d "${MIP_METRICS_DIR}" ]; then
    local f="$MIP_METRICS_DIR/mip_weekly.prom" now last_ok
    now="$(date +%s)"
    last_ok="$(awk '/^mip_weekly_last_success_timestamp_seconds /{print $2}' "$f" 2>/dev/null)"
    [ "$FAILED_N" -eq 0 ] && last_ok="$now"
    {
      echo "# HELP mip_weekly_last_run_timestamp_seconds When the last weekly refresh ended."
      echo "# TYPE mip_weekly_last_run_timestamp_seconds gauge"
      echo "mip_weekly_last_run_timestamp_seconds $now"
      echo "# HELP mip_weekly_last_run_failed_steps Failed steps in the last weekly refresh (0 = clean)."
      echo "# TYPE mip_weekly_last_run_failed_steps gauge"
      echo "mip_weekly_last_run_failed_steps $FAILED_N"
      echo "# HELP mip_weekly_last_run_warnings Warnings (e.g. failed data-quality checks) in the last weekly refresh."
      echo "# TYPE mip_weekly_last_run_warnings gauge"
      echo "mip_weekly_last_run_warnings $WARN_N"
      if [ -n "$last_ok" ]; then
        echo "# HELP mip_weekly_last_success_timestamp_seconds Last weekly refresh with zero failed steps."
        echo "# TYPE mip_weekly_last_success_timestamp_seconds gauge"
        echo "mip_weekly_last_success_timestamp_seconds $last_ok"
      fi
    } > "$f.$$" && chmod 644 "$f.$$" && mv -f "$f.$$" "$f"
  fi
  [ "$WARN_N" -eq 0 ] || printf '== %s warning(s):\n%s' "$WARN_N" "$WARN_LIST"
  if [ "$FAILED_N" -eq 0 ]; then
    echo "== weekly refresh finished OK $(date -u)"
    date -u +%FT%TZ > "$LOGS/weekly_last_success"   # read by scripts/weekly_if_due.sh (catch-up after a missed Sunday)
    exit 0
  fi
  printf '== weekly refresh FAILED %s: %s failed step(s):\n%s' "$(date -u)" "$FAILED_N" "$FAILED_LIST"
  echo "== no success marker written: the catch-up will retry (re-runs resume; fetch claims go stale after 30 min)"
  exit 1
}

# The platform database lives on the homelab server (since M4.9). On the Mac it is reached through the persistent ssh
# tunnel on 127.0.0.1:15434 (launchd agent com.dhakakacchi.homelab-tunnel); on the server the container connects
# directly. The Mac's own mip-postgres is retired: never start it.
# dbt reads its connection from MIP_PG_* (dbt/profiles.yml); `uv run` does not load .env, so load just those names here.
while IFS= read -r line; do export "${line%%=*}=${line#*=}"; done < <(grep -E '^MIP_PG_(HOST|PORT|USER|DB|PASSWORD)=' "$ENV_FILE" 2>/dev/null)  # split at the FIRST '=' only
mip_db_check() { # the database answers and is called mip; prints no credentials
  "${PY_ARR[@]}" - <<'PY'
import os, sys
import psycopg
try:
    with psycopg.connect(host=os.environ["MIP_PG_HOST"], port=int(os.environ["MIP_PG_PORT"]), user=os.environ["MIP_PG_USER"],
                         password=os.environ["MIP_PG_PASSWORD"], dbname=os.environ["MIP_PG_DB"], connect_timeout=8) as c:
        db = c.execute("select current_database()").fetchone()[0]
except KeyError as e:
    sys.exit(f"MIP_PG_{e.args[0].removeprefix('MIP_PG_')} is not set")
except Exception as e:
    sys.exit(f"cannot reach the mip database ({type(e).__name__})")
sys.exit(0 if db == "mip" else f"the database answering is '{db}', not 'mip'")
PY
}
mip_ready=0
CHECK_ERR="${TMPDIR:-/tmp}/.mip_db_check.$$"
for _ in $(seq 1 "${MIP_PREFLIGHT_TRIES:-10}"); do
  mip_db_check 2>"$CHECK_ERR" && { mip_ready=1; break; }
  [ "${MIP_PREFLIGHT_TRIES:-10}" -gt 1 ] && sleep 9
done
if [ "$mip_ready" != 1 ]; then
  hint="restart the tunnel: launchctl kickstart -k gui/$(id -u)/com.dhakakacchi.homelab-tunnel"
  [ -f /.dockerenv ] && hint="check that mip-postgres is up and this container is on its network"
  fail "preflight: $(tail -1 "$CHECK_ERR" 2>/dev/null) -- $hint"
  rm -f "$CHECK_ERR"
  finish
fi
rm -f "$CHECK_ERR"

run mip db partitions
# VPS collector configured? Then the light API sources were collected there all week: import them, and only run the
# heavy / bot-protected sources here. YouTube: statistics refresh of known videos only (the VPS does the searching).
if [ -n "${MIP_COLLECTOR_DSN:-}" ] || grep -q '^MIP_COLLECTOR_DSN=.' "$ENV_FILE" 2>/dev/null; then
  COLLECTOR=1
  run mip collector import
  LOCAL_SOURCES="wolt lieferando first_party youtube"
  export MIP_YOUTUBE_SEARCHES=none
else
  COLLECTOR=0
  LOCAL_SOURCES="wolt lieferando first_party wikipedia reddit_archive youtube berlin_events"
fi
for s in $LOCAL_SOURCES; do
  run mip discover -m "$M" -s "$s" --refresh
done

# Crawls run in parallel; each one's exit status is collected (a lost DB connection makes `mip fetch` exit 1).
BG_PIDS=""; BG_NAMES=""
bg() { local name="$1"; shift; echo "== $(date -u +%F' '%H:%M) [background] $* > $L/$name.log"
       "$@" > "$L/$name.log" 2>&1 & BG_PIDS="$BG_PIDS $!"; BG_NAMES="$BG_NAMES $name"; }
bg wolt       mip fetch -m "$M" -s wolt -w 8 --skip-health --refresh-children
bg lieferando mip fetch -m "$M" -s lieferando -w 8 --skip-health --refresh-children
bg first_party mip fetch -m "$M" -s first_party -w 1 --skip-health
if [ "$COLLECTOR" != 1 ]; then
  bg wikipedia     mip fetch -m "$M" -s wikipedia -w 3 --skip-health
  bg reddit        mip fetch -m "$M" -s reddit_archive -w 2 --skip-health
  bg berlin_events mip fetch -m "$M" -s berlin_events -w 1 --skip-health
fi
if mip healthcheck -m "$M" -s youtube > /dev/null 2>&1; then          # needs YOUTUBE_API_KEY
  bg youtube mip fetch -m "$M" -s youtube -w 2 --refresh-children
else
  warn "youtube healthcheck failed: YouTube refresh skipped"
fi
# shellcheck disable=SC2086  # split the space-separated names on purpose
set -- $BG_NAMES
for pid in $BG_PIDS; do
  wait "$pid"; rc=$?
  [ "$rc" -eq 0 ] || fail "fetch $1 (exit $rc; see $L/$1.log)"
  shift
done
echo "== $(date -u +%F' '%H:%M) crawls finished"

if mip healthcheck -m "$M" -s instagram_graph > /dev/null 2>&1; then
  run mip discover -m "$M" -s instagram_graph --refresh
  run mip fetch -m "$M" -s instagram_graph -w 1 --refresh-children
fi
run mip resolve listings
run mip transform; TRANSFORM_RC=$?
run mip enrich languages
run mip enrich content
run dbt build --project-dir dbt --profiles-dir dbt --select content_tag+ --exclude feature_business feature_offering

echo "== $(date -u +%F' '%H:%M) mip report -m $M"
mip report -m "$M" 2>&1 | tee "$L/report.log"; rc=${PIPESTATUS[0]}
case "$rc" in
  0) ;;
  3) warn "mip report: $(grep -Eo '[0-9]+ failed check\(s\)' "$L/report.log" | tail -1 || echo 'some') (data quality; see ops.quality_report and $L/report.log)" ;;
  *) fail "mip report crashed (exit $rc; see $L/report.log)" ;;
esac

# A training-set version is only exported from a complete, freshly built week: after any failure the retry exports.
if [ "$FAILED_N" -eq 0 ]; then
  run mip ml export business_features
  run mip ml export offering_features
  run mip ml export content_features
else
  echo "== ML exports skipped: $FAILED_N step(s) failed earlier (transform exit ${TRANSFORM_RC})"
fi
finish
