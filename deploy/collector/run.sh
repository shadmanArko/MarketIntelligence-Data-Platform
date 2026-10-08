#!/usr/bin/env bash
# Host cron entry for the VPS collector (deploy user). Same platform code as the Mac, light API sources only:
#   daily : YouTube recent-upload searches (+ the videos/channels/comments they lead to), Berlin events
#   weekly: Wikipedia pageviews, Reddit's last 3 months (Saturday night, before the Mac imports on Sunday)
# crontab:
#   15 10 * * *  /opt/dhaka-kacchi/mip-collector/deploy/collector/run.sh daily  >> /opt/dhaka-kacchi/logs/mip-collector.log 2>&1
#   30 22 * * 6  /opt/dhaka-kacchi/mip-collector/deploy/collector/run.sh weekly >> /opt/dhaka-kacchi/logs/mip-collector.log 2>&1
set -uo pipefail
cd "$(dirname "$0")"
M=berlin-food
mip() { docker compose run --rm --no-deps collector "$@"; }
run() { echo "== $(date -u +%FT%TZ) $*"; mip "$@" || echo "!! failed: $*"; }

docker compose up -d --wait collector-db > /dev/null
run db migrate
run db partitions
case "${1:-daily}" in
  daily)
    docker compose run --rm --no-deps -e MIP_YOUTUBE_SEARCHES=recent collector discover -m "$M" -s youtube \
      || echo "!! failed: youtube discover"
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
echo "== $(date -u +%FT%TZ) done"
