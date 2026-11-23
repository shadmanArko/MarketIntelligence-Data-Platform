#!/usr/bin/env bash
# ExecStartPre of mip-weekly.service: postpone the weekly job while the server is short of memory.
# Waits (checking every CHECK_MIN minutes, up to MAX_WAIT_MIN) until MemAvailable >= MIN_FREE_GIB, then lets the job
# start. Still short after MAX_WAIT_MIN: exits 75 (EX_TEMPFAIL); the unit fails and systemd retries after RestartSec.
# The container is capped at 6 GiB (compose mem_limit); the default leaves 2 GiB headroom for everything else.
set -uo pipefail
MIN_FREE_GIB="${MIN_FREE_GIB:-8}"
MAX_WAIT_MIN="${MAX_WAIT_MIN:-120}"
CHECK_MIN="${CHECK_MIN:-5}"
need_kib=$((MIN_FREE_GIB * 1024 * 1024))
waited=0
while :; do
  avail_kib="$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)"
  if [ "${avail_kib:-0}" -ge "$need_kib" ]; then
    echo "ram_guard: MemAvailable $((avail_kib / 1024 / 1024)) GiB >= ${MIN_FREE_GIB} GiB: starting"
    exit 0
  fi
  if [ "$waited" -ge "$MAX_WAIT_MIN" ]; then
    echo "ram_guard: MemAvailable $((avail_kib / 1024 / 1024)) GiB < ${MIN_FREE_GIB} GiB after ${waited} min: postponing (unit fails, systemd retries)"
    exit 75
  fi
  echo "ram_guard: MemAvailable $((avail_kib / 1024 / 1024)) GiB < ${MIN_FREE_GIB} GiB: waiting ${CHECK_MIN} min"
  sleep "$((CHECK_MIN * 60))"
  waited=$((waited + CHECK_MIN))
done
