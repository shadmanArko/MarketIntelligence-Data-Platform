# mip weekly refresh on the homelab server

The same `scripts/weekly_refresh.sh` the Mac runs, in a container on the server, so the weekly crawl and rebuild no
longer depend on the Mac being awake, on AC power and holding an ssh tunnel.

| File | What |
|---|---|
| `Dockerfile` | Python 3.13 + uv + dbt; non-root uid 10003; tini as PID 1; no browser (`WITH_CHROMIUM=1` adds Chromium for playwright, which only `google_maps` uses, not the weekly job) |
| `compose.yaml` | the `weekly` batch service: no ports, `cap_drop: ALL`, `no-new-privileges`, 4 CPU / 6 GiB, secrets as files, log rotation, DB health check; joins mip-postgres' network + its own egress bridge |
| `entrypoint.sh` | secret files -> the environment the code reads; builds `MIP_DATABASE_URL` from `MIP_PG_*` + the password file |
| `healthcheck.py` | unhealthy while the mip database does not answer |
| `mip-weekly.service` / `.timer` | Sunday 01:00 Europe/Berlin, `Persistent=true`; RAM guard; max 24 h; failed week retried after 6 h (max 3 starts / 2 days) |
| `ram_guard.sh` | waits up to 2 h for `MemAvailable >= 8 GiB`, else postpones (unit fails, systemd retries) |
| `.env.example` | non-secret settings for `/srv/apps/mip-weekly/weekly.env` |

## Success means success
`weekly_refresh.sh` exits 1 and writes **no** `weekly_last_success` when any step fails (preflight, a crawl that lost
its DB connection, transform, enrich, the content dbt build, ML export, or a `mip report` crash). Failed data-quality
checks (`mip report` exit 3) are warnings: counted in `weekly_last_status`, not a failed week. After a failure the ML
exports are skipped (the retry exports a complete week). Every run writes `logs/weekly_last_status`; with
`MIP_METRICS_DIR` it also writes `mip_weekly.prom` gauges (last run, last success, failed steps, warnings).

## Outputs and how the owner gets them
Everything the job writes is on the server's HDD under `/srv/data/mip-weekly/` (`/app/data` in the container):
`ml/<name>/vNNNN/` training-set exports (registered in `ml.training_sets`, whose `path` starts with `/app/data`),
`logs/weekly_YYYYMMDD/` per-run logs, `logs/weekly_last_status`, `cache/` (rebuildable). The database results
(raw, core, marts, ml schemas) are in `mip` as before. On the Mac, `scripts/pull_server_outputs.sh` pulls new
export versions into `data/ml/` and the logs into `data/logs/server/` (read-only rsync); that is also the off-server
copy of the exports.

## Run by hand (server)
```bash
cd /srv/apps/mip-weekly/repo/deploy/weekly
docker compose --env-file /srv/apps/mip-weekly/weekly.env run --rm --no-deps --name mip-weekly-run weekly          # full week
docker compose --env-file /srv/apps/mip-weekly/weekly.env run --rm --no-deps weekly mip status                      # any mip command
```
Never run the Mac's `weekly_refresh.sh` while the server job runs (`systemctl is-active mip-weekly.service`): both
crawl from the same home connection.
