-- Read-only role for analysts, notebooks, BI tools, LLM agents: can read the clean layers, cannot change anything.
-- raw / ops stay with the owner; staging views are readable (they execute with the owner's rights).
-- Tenant tables keep row-level security: without `SET app.tenant_id` the reader sees none of their rows.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mip_reader') THEN
    CREATE ROLE mip_reader LOGIN PASSWORD 'mip_reader' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END $$;
ALTER ROLE mip_reader SET default_transaction_read_only = on;
ALTER ROLE mip_reader SET statement_timeout = '5min';
GRANT CONNECT ON DATABASE mip TO mip_reader;
GRANT USAGE ON SCHEMA core, marts, ml, staging TO mip_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA core, marts, ml, staging TO mip_reader;
-- dbt recreates tables on every build: grant on future tables too
ALTER DEFAULT PRIVILEGES FOR ROLE mip IN SCHEMA core, marts, ml, staging GRANT SELECT ON TABLES TO mip_reader;
