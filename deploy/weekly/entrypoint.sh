#!/usr/bin/env bash
# Turns the Compose secret files (/run/secrets/<name>, mode 600 on the host) into the environment the mip code reads,
# for this process tree only. Nothing is printed: never echo a value here.
#   <name>            -> exported as <NAME> (upper case), e.g. youtube_api_key -> YOUTUBE_API_KEY; empty file = unset
#   *_ssh_key         -> not exported; the path is used instead (collector_ssh_key -> MIP_COLLECTOR_SSH_KEY)
#   mip_pg_password   -> MIP_PG_PASSWORD (dbt) and MIP_DATABASE_URL built from MIP_PG_HOST/PORT/USER/DB (python code)
set -euo pipefail
SECRETS="${MIP_SECRETS_DIR:-/run/secrets}"

if [ -d "$SECRETS" ]; then
  for f in "$SECRETS"/*; do
    [ -f "$f" ] || continue
    name="$(basename "$f")"
    case "$name" in
      *_ssh_key) continue ;;
    esac
    value="$(cat "$f")"            # trailing newlines are stripped by $(...)
    [ -n "$value" ] || continue
    export "$(printf '%s' "$name" | tr '[:lower:]' '[:upper:]')=$value"
  done
fi
[ -f "$SECRETS/collector_ssh_key" ] && export MIP_COLLECTOR_SSH_KEY="$SECRETS/collector_ssh_key"

if [ -n "${MIP_PG_PASSWORD:-}" ] && [ -z "${MIP_DATABASE_URL:-}" ]; then
  MIP_DATABASE_URL="$("${PY_CMD:-python}" - <<'PY'
import os
from urllib.parse import quote
e = os.environ
print(f"postgresql://{quote(e['MIP_PG_USER'], safe='')}:{quote(e['MIP_PG_PASSWORD'], safe='')}"
      f"@{e['MIP_PG_HOST']}:{e['MIP_PG_PORT']}/{quote(e['MIP_PG_DB'], safe='')}")
PY
)"
  export MIP_DATABASE_URL
fi

exec "$@"
