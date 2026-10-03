#!/usr/bin/env bash
# Weekly snapshot: re-observe every delivery listing, fee, menu price and new review, plus first-party data and
# Wikipedia interest, Reddit / YouTube / Berlin events, then rebuild, test, report and export a new training-set version. Every run adds new
# timestamped observations (raw is append-only), which is what turns the platform into a time series.
# Scheduled by ~/Library/LaunchAgents/com.dhakakacchi.mip.weekly.plist (Sundays 01:00); safe to run by hand.
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
M=berlin-food
L=data/logs/weekly_$(date +%Y%m%d)
mkdir -p "$L"
run() { echo "== $(date -u +%F' '%H:%M) $*"; "$@" || echo "!! failed: $*"; }

docker compose up -d --wait > /dev/null 2>&1
run uv run mip db partitions
for s in wolt lieferando first_party wikipedia reddit_archive youtube berlin_events; do
  run uv run mip discover -m "$M" -s "$s" --refresh
done
uv run mip fetch -m "$M" -s wolt -w 8 --skip-health --refresh-children       > "$L/wolt.log" 2>&1 &
uv run mip fetch -m "$M" -s lieferando -w 8 --skip-health --refresh-children > "$L/lieferando.log" 2>&1 &
uv run mip fetch -m "$M" -s first_party -w 1 --skip-health                   > "$L/first_party.log" 2>&1 &
uv run mip fetch -m "$M" -s wikipedia -w 3 --skip-health                     > "$L/wikipedia.log" 2>&1 &
uv run mip fetch -m "$M" -s reddit_archive -w 2 --skip-health                > "$L/reddit.log" 2>&1 &
uv run mip fetch -m "$M" -s berlin_events -w 1 --skip-health                 > "$L/berlin_events.log" 2>&1 &
if uv run mip healthcheck -m "$M" -s youtube > /dev/null 2>&1; then          # needs YOUTUBE_API_KEY
  uv run mip fetch -m "$M" -s youtube -w 2 --refresh-children                > "$L/youtube.log" 2>&1 &
fi
wait
if uv run mip healthcheck -m "$M" -s instagram_graph > /dev/null 2>&1; then
  run uv run mip discover -m "$M" -s instagram_graph --refresh
  run uv run mip fetch -m "$M" -s instagram_graph -w 1 --refresh-children
fi
run uv run mip resolve listings
run uv run mip transform
run uv run mip enrich languages
run uv run mip enrich content
(cd dbt && run uv run dbt build --select content_tag+ --exclude feature_business feature_offering)
run uv run mip report -m "$M"
run uv run mip ml export business_features
run uv run mip ml export offering_features
run uv run mip ml export content_features
echo "== weekly refresh finished $(date -u)"
