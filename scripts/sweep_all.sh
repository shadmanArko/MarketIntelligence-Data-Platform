#!/usr/bin/env bash
# Full Berlin sweep of the free sources. Resumable: rerun after any crash, it continues where it stopped.
set -u
cd "$(dirname "$0")/.."
L=data/logs
uv run mip fetch -s wolt -e coverage -w 2 --skip-health                                > $L/wolt_coverage.log 2>&1 &
uv run mip fetch -s wolt -e venue_static -e menu -e venue_dynamic -w 6 --skip-health   > $L/wolt_venues.log 2>&1 &
uv run mip fetch -s lieferando -w 8 --skip-health                                      > $L/lieferando.log 2>&1 &
uv run mip fetch -s google_maps -w 3                                                   > $L/google_maps.log 2>&1 &
wait
# second pass: picks up follow-up work discovered late and retries anything that failed
for s in wolt lieferando google_maps; do uv run mip fetch -s $s -w 8 --skip-health > $L/${s}_pass2.log 2>&1; done
