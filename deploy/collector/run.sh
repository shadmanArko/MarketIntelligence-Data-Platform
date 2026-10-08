#!/usr/bin/env bash
# Host cron entry for the VPS collector (deploy user). Same platform code as the Mac, light API sources only:
#   daily : YouTube recent-upload searches (+ the videos/channels/comments they lead to), Berlin events
#   weekly: Wikipedia pageviews, Reddit's last 3 months (Saturday night, before the Mac imports on Sunday)
# crontab:
#   15 10 * * *  /opt/dhaka-kacchi/mip-collector/deploy/collector/run.sh daily  >> /opt/dhaka-kacchi/logs/mip-collector.log 2>&1
#   30 22 * * 6  /opt/dhaka-kacchi/mip-collector/deploy/collector/run.sh weekly >> /opt/dhaka-kacchi/logs/mip-collector.log 2>&1
set -uo pipefail
cd "$(dirname "$0")" || exit 1
M=berlin-food
JOB="${1:-daily}"
FAILED=0
mip() { docker compose run --rm --no-deps collector "$@"; }
run() { echo "== $(date -u +%FT%TZ) $*"; mip "$@" || { echo "!! failed: $*"; FAILED=$((FAILED + 1)); }; }

# Publish the run's result for the VPS monitoring (node-exporter textfile collector, dk-intelligence ADR 0016).
# A run counts as clean only with zero failed steps; the last clean time is kept across failed runs.
publish() {
  local dir="${INTEL_METRICS_DIR:-/opt/dhaka-kacchi/metrics}" now last_ok
  [[ -d "$dir" ]] || return 0
  now="$(date +%s)"
  last_ok="$(grep -E "^mip_collector_last_success_timestamp_seconds\{job=\"$JOB\"\}" "$dir/mip_collector_$JOB.prom" 2>/dev/null | awk '{print $2}')"
  [[ "$FAILED" -eq 0 ]] && last_ok="$now"
  {
    echo "# HELP mip_collector_last_run_timestamp_seconds When the last collector run ended."
    echo "# TYPE mip_collector_last_run_timestamp_seconds gauge"
    echo "mip_collector_last_run_timestamp_seconds{job=\"$JOB\"} $now"
    echo "# HELP mip_collector_last_run_failed_steps Failed steps in the last run (0 = clean)."
    echo "# TYPE mip_collector_last_run_failed_steps gauge"
    echo "mip_collector_last_run_failed_steps{job=\"$JOB\"} $FAILED"
    if [[ -n "$last_ok" ]]; then
      echo "# HELP mip_collector_last_success_timestamp_seconds Last run with zero failed steps."
      echo "# TYPE mip_collector_last_success_timestamp_seconds gauge"
      echo "mip_collector_last_success_timestamp_seconds{job=\"$JOB\"} $last_ok"
    fi
  } > "$dir/.mip_collector_$JOB.prom.$$" && chmod 644 "$dir/.mip_collector_$JOB.prom.$$" \
    && mv -f "$dir/.mip_collector_$JOB.prom.$$" "$dir/mip_collector_$JOB.prom"
}

docker compose up -d --wait collector-db > /dev/null
run db migrate
run db partitions
case "$JOB" in
  daily)
    docker compose run --rm --no-deps -e MIP_YOUTUBE_SEARCHES=recent collector discover -m "$M" -s youtube \
      || { echo "!! failed: youtube discover"; FAILED=$((FAILED + 1)); }
    run fetch -m "$M" -s youtube -w 2
    run discover -m "$M" -s berlin_events --refresh
    run fetch -m "$M" -s berlin_events -w 1 --skip-health
    ;;
  weekly)
    run discover -m "$M" -s wikipedia --refresh
    run fetch -m "$M" -s wikipedia -w 3 --skip-health
    run discover -m "$M" -s reddit_archive --refresh      # refresh = only the last ~3 months
    run fetch -m "$M" -s reddit_archive -w 2 --skip-health
    ;;
esac
run status
publish
echo "== $(date -u +%FT%TZ) done ($FAILED failed step(s))"
