#!/usr/bin/env bash
# Full Berlin delivery-app sweep. Resumable: rerun after any crash, it continues where it stopped.
set -u
cd "$(dirname "$0")/.."
L=data/logs
uv run mip fetch -s wolt -e coverage -w 2 --skip-health                                > $L/wolt_coverage.log 2>&1 &
uv run mip fetch -s wolt -e venue_static -e menu -e venue_dynamic -w 6 --skip-health   > $L/wolt_venues.log 2>&1 &
uv run mip fetch -s lieferando -w 8 --skip-health                                      > $L/lieferando.log 2>&1 &
wait
# second pass: picks up venues discovered late by the coverage worker
uv run mip fetch -s wolt -w 8 --skip-health > $L/wolt_pass2.log 2>&1
uv run mip fetch -s lieferando -w 8 --skip-health > $L/lieferando_pass2.log 2>&1
