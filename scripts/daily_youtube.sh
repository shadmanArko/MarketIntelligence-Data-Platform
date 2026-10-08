#!/usr/bin/env bash
# Daily: spend YouTube's free search quota (~90 searches, resets at midnight Pacific = 09:00 Berlin) and read
# whatever videos / channels / comments those searches lead to. Weekly statistics snapshots run in weekly_refresh.sh.
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if grep -q '^MIP_COLLECTOR_DSN=.' .env 2>/dev/null; then
  echo "YouTube searches run daily on the VPS collector; nothing to do here."; exit 0
fi
docker compose up -d --wait > /dev/null 2>&1
uv run mip discover -m berlin-food -s youtube
uv run mip fetch -m berlin-food -s youtube -w 2
