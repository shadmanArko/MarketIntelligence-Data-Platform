#!/usr/bin/env bash
# Mac side of the server weekly job (deploy/weekly): copy its ML training-set exports and logs from the server into
# this checkout's data/, read-only from the server's point of view (rsync pull; nothing on the server changes).
#   data/ml/<name>/v<NNNN>/   new versions only (versions come from ml.training_sets, so they never collide with
#                             versions exported on the Mac). ml.training_sets.path says /app/data/ml/...: replace
#                             the /app/data prefix with this checkout's data/ to find the files.
#   data/logs/server/         the server's weekly_* run logs and weekly_last_status
# This is also the off-server copy of the exports (the server has no off-site backup).
#
# Needs in .env (names only; no secrets): MIP_SERVER_SSH=<user>@<server tailscale ip>, optional MIP_SERVER_SSH_KEY,
# optional MIP_SERVER_DATA (default /srv/data/mip-weekly).
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1
get() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }
HOST="${MIP_SERVER_SSH:-$(get MIP_SERVER_SSH)}"
KEY="${MIP_SERVER_SSH_KEY:-$(get MIP_SERVER_SSH_KEY)}"
REMOTE="${MIP_SERVER_DATA:-$(get MIP_SERVER_DATA)}"; REMOTE="${REMOTE:-/srv/data/mip-weekly}"
[ -n "$HOST" ] || { echo "set MIP_SERVER_SSH=<user>@<host> in .env" >&2; exit 2; }
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15)
[ -n "$KEY" ] && SSH+=(-i "${KEY/#\~/$HOME}" -o IdentitiesOnly=yes)

mkdir -p data/ml data/logs/server
echo "== pulling ML exports from $REMOTE/ml"
rsync -a --ignore-existing -e "${SSH[*]}" "$HOST:$REMOTE/ml/" data/ml/
echo "== pulling run logs from $REMOTE/logs"
rsync -a -e "${SSH[*]}" "$HOST:$REMOTE/logs/" data/logs/server/   # only the weekly job writes there
echo "== server's last weekly run:"
cat data/logs/server/weekly_last_status 2>/dev/null || echo "(no status yet)"
