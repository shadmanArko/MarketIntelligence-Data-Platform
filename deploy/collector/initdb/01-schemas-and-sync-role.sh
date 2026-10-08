#!/bin/sh
# Runs once, when the collector database is first created.
# - empty core/marts/ml/staging schemas: the platform's reader-role migration grants on them (nothing else lives there)
# - mip_sync: the read-only login the Mac's `mip collector import` uses (raw.* and ops.runs only)
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
CREATE SCHEMA IF NOT EXISTS raw; CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS core; CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS ml; CREATE SCHEMA IF NOT EXISTS staging;
CREATE ROLE mip_sync LOGIN PASSWORD '${MIP_SYNC_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER ROLE mip_sync SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO mip_sync;
GRANT USAGE ON SCHEMA raw, ops TO mip_sync;
ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA raw GRANT SELECT ON TABLES TO mip_sync;
ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA ops GRANT SELECT ON TABLES TO mip_sync;
SQL
