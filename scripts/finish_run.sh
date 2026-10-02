#!/usr/bin/env bash
# Waits for every running `mip fetch` to finish, then completes the run: late discovery, resolution, full dbt
# build with tests, social linking, enrichment, quality report and fresh versioned training sets.
set -uo pipefail
cd "$(dirname "$0")/.."
M=${1:-berlin-food}
L=data/logs
while pgrep -f "bin/mip fetch" > /dev/null; do sleep 120; done
run() { echo "== $(date -u +%H:%M) $*"; "$@" || echo "!! failed: $*"; }

# second pass over anything that failed or was discovered late
for s in wolt lieferando google_maps web_crawl; do run uv run mip fetch -m "$M" -s "$s" -w 6 --skip-health; done
run uv run mip transform --select "staging core.int_listing_observation core.listing core.listing_cuisine core.int_offering_observation core.offering"
run uv run mip resolve listings
run uv run mip transform --select "core"
run uv run mip discover -m "$M" -s tiktok
run uv run mip fetch -m "$M" -s tiktok -w 2 --skip-health
if uv run mip healthcheck -m "$M" -s instagram_graph; then
  run uv run mip discover -m "$M" -s instagram_graph
  run uv run mip fetch -m "$M" -s instagram_graph -w 1
fi
run uv run mip transform --select "staging core"
run uv run mip resolve social
run uv run mip enrich mentions
run uv run mip enrich languages
run uv run mip transform
run uv run mip report -m "$M"
run uv run mip ml export business_features
run uv run mip ml export offering_features
echo "== finished $(date -u)"
