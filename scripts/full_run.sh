#!/usr/bin/env bash
# One complete market run (Phase 5): bulk datasets -> every enabled free source -> resolution -> enrichment ->
# dbt build with tests -> quality report -> versioned training sets. Resumable: rerun after any interruption.
set -uo pipefail
cd "$(dirname "$0")/.."
M=${1:-berlin-food}
L=data/logs
mkdir -p "$L"
run() { echo "== $*"; "$@" || echo "!! failed: $*"; }

run uv run mip db migrate
run uv run mip db partitions
run uv run mip geo grid -m "$M"
run uv run mip taxonomy -m "$M"
for ds in osm overture zensus holidays weather crux; do run uv run mip datasets load "$ds" -m "$M"; done

# master list first: everything social / web / search depends on it
for s in wolt lieferando google_maps; do
  run uv run mip discover -m "$M" -s "$s"
done
uv run mip fetch -m "$M" -s wolt -w 8 --skip-health        > "$L/wolt.log" 2>&1 &
uv run mip fetch -m "$M" -s lieferando -w 8 --skip-health  > "$L/lieferando.log" 2>&1 &
uv run mip fetch -m "$M" -s google_maps -w 1               > "$L/google_maps.log" 2>&1 &
wait

run uv run mip transform --select "staging core.int_listing_observation core.listing core.listing_cuisine core.offering"
run uv run mip resolve listings
run uv run mip transform --select "core"

# web, social, search (need business websites and handles from the master list)
run uv run mip discover -m "$M" -s web_crawl
run uv run mip fetch -m "$M" -s web_crawl -w 24 --skip-health
run uv run mip discover -m "$M" -s tiktok
run uv run mip fetch -m "$M" -s tiktok -w 2 --skip-health
if uv run mip healthcheck -m "$M" -s instagram_graph; then
  run uv run mip discover -m "$M" -s instagram_graph
  run uv run mip fetch -m "$M" -s instagram_graph -w 1
fi
run uv run mip discover -m "$M" -s serp
run uv run mip fetch -m "$M" -s serp -w 1 --skip-health

run uv run mip transform --select "staging core"
run uv run mip resolve social
run uv run mip enrich mentions
run uv run mip enrich languages
run uv run mip transform                       # full build: staging -> core -> marts -> ml, all tests
run uv run mip report -m "$M"
run uv run mip ml export business_features
run uv run mip ml export offering_features
echo "== done"
