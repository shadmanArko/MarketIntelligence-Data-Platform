-- Migrations own the raw and ops schemas; dbt owns everything after raw.
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS raw;

-- ---------------------------------------------------------------- ops: runs
CREATE TABLE ops.runs (
  run_id        uuid        PRIMARY KEY DEFAULT uuidv7(),
  market_id     text        NOT NULL,
  source        text        NOT NULL,
  command       text        NOT NULL,              -- discover | fetch | transform | ...
  status        text        NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'succeeded', 'failed', 'aborted')),
  started_at    timestamptz NOT NULL DEFAULT now(),
  ended_at      timestamptz,
  git_commit    text,
  config_hash   text,
  args          jsonb       NOT NULL DEFAULT '{}',
  metrics       jsonb       NOT NULL DEFAULT '{}', -- requests, status classes, records, bytes, quarantined
  error         text
);
CREATE INDEX ON ops.runs (market_id, source, started_at DESC);

-- ---------------------------------------------------------------- ops: work queue
CREATE TABLE ops.tasks (
  task_id         uuid        PRIMARY KEY DEFAULT uuidv7(),
  task_key        text        NOT NULL UNIQUE,      -- deterministic: market|source|entity_type|params
  market_id       text        NOT NULL,
  source          text        NOT NULL,
  entity_type     text        NOT NULL,
  natural_key     text        NOT NULL,
  params          jsonb       NOT NULL DEFAULT '{}',
  priority        smallint    NOT NULL DEFAULT 100,
  status          text        NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'running', 'done', 'failed', 'dead')),
  attempts        smallint    NOT NULL DEFAULT 0,
  max_attempts    smallint    NOT NULL DEFAULT 6,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  claimed_by      text,
  claimed_at      timestamptz,
  last_run_id     uuid        REFERENCES ops.runs,
  last_error      text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  parent_task_id  uuid
);
CREATE INDEX tasks_claim_idx ON ops.tasks (market_id, source, status, priority, next_attempt_at)
  WHERE status IN ('pending', 'failed');

-- ---------------------------------------------------------------- ops: gate 1 failures
CREATE TABLE ops.quarantine (
  quarantine_id uuid        PRIMARY KEY DEFAULT uuidv7(),
  run_id        uuid        REFERENCES ops.runs,
  source        text        NOT NULL,
  entity_type   text        NOT NULL,
  natural_key   text,
  reason        text        NOT NULL,
  errors        jsonb,
  request_meta  jsonb,
  http_status   smallint,
  payload       jsonb,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON ops.quarantine (source, entity_type, created_at DESC);

CREATE TABLE ops.schema_known_fields (
  source      text NOT NULL,
  entity_type text NOT NULL,
  field_path  text NOT NULL,
  first_seen  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source, entity_type, field_path)
);

CREATE TABLE ops.schema_drift (
  drift_id     uuid        PRIMARY KEY DEFAULT uuidv7(),
  run_id       uuid        REFERENCES ops.runs,
  source       text        NOT NULL,
  entity_type  text        NOT NULL,
  field_path   text        NOT NULL,
  kind         text        NOT NULL CHECK (kind IN ('new_field', 'missing_required', 'type_change')),
  example      jsonb,
  detected_at  timestamptz NOT NULL DEFAULT now(),
  acknowledged boolean     NOT NULL DEFAULT false
);

CREATE TABLE ops.connector_health (
  checked_at  timestamptz NOT NULL DEFAULT now(),
  source      text        NOT NULL,
  ok          boolean     NOT NULL,
  latency_ms  integer,
  detail      text,
  PRIMARY KEY (source, checked_at)
);

-- ---------------------------------------------------------------- ops: dataset registry
CREATE TABLE ops.datasets (
  dataset_id    uuid        PRIMARY KEY DEFAULT uuidv7(),
  name          text        NOT NULL,             -- e.g. overture_places
  version       text        NOT NULL,             -- e.g. 2026-09-17.0
  source_url    text        NOT NULL,
  release_date  date,
  checksum      text,
  terms         text,
  row_count     bigint,
  raw_table     text,                             -- e.g. raw.ds_overture_places_2026_09
  local_path    text,
  refresh_cadence text,
  loaded_at     timestamptz NOT NULL DEFAULT now(),
  meta          jsonb       NOT NULL DEFAULT '{}',
  UNIQUE (name, version)
);

-- ---------------------------------------------------------------- ops: quality report per run
CREATE TABLE ops.quality_report (
  report_id    uuid        PRIMARY KEY DEFAULT uuidv7(),
  run_id       uuid        REFERENCES ops.runs,
  market_id    text        NOT NULL,
  source       text        NOT NULL,
  entity_type  text        NOT NULL,
  metric       text        NOT NULL,              -- completeness:<field> | row_count | freshness_h | quarantined
  value        double precision,
  previous     double precision,
  passed       boolean     NOT NULL,
  detail       text,
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- raw: content-addressed payloads
CREATE TABLE raw.payloads (
  payload_sha256 bytea       PRIMARY KEY,
  payload        jsonb       NOT NULL,
  byte_size      integer     NOT NULL,
  first_seen_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE raw.observations (
  observation_id uuid        NOT NULL DEFAULT uuidv7(),
  market_id      text        NOT NULL,
  source         text        NOT NULL,
  entity_type    text        NOT NULL,
  natural_key    text        NOT NULL,
  run_id         uuid        NOT NULL REFERENCES ops.runs,
  task_id        uuid,
  connector_ver  text        NOT NULL,
  request_meta   jsonb       NOT NULL,
  http_status    smallint    NOT NULL,
  payload_sha256 bytea       NOT NULL REFERENCES raw.payloads,
  fetched_at     timestamptz NOT NULL,
  PRIMARY KEY (observation_id, fetched_at)
) PARTITION BY RANGE (fetched_at);

CREATE INDEX ON raw.observations (source, entity_type, natural_key, fetched_at DESC);
CREATE INDEX ON raw.observations USING brin (fetched_at);
CREATE INDEX ON raw.observations (run_id);

CREATE TABLE raw.observations_default PARTITION OF raw.observations DEFAULT;

-- One partition per month; called by the platform before each run.
CREATE FUNCTION ops.ensure_month_partition(p_table regclass, p_month date)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  start_d date := date_trunc('month', p_month)::date;
  end_d   date := (date_trunc('month', p_month) + interval '1 month')::date;
  part    text := p_table::text || '_' || to_char(start_d, 'YYYY_MM');
BEGIN
  IF to_regclass(part) IS NULL THEN
    EXECUTE format('CREATE TABLE %s PARTITION OF %s FOR VALUES FROM (%L) TO (%L)',
                   part, p_table, start_d, end_d);
  END IF;
END $$;

DO $$
DECLARE m date;
BEGIN
  FOR m IN SELECT generate_series(date '2026-01-01', date '2027-12-01', interval '1 month')::date LOOP
    PERFORM ops.ensure_month_partition('raw.observations', m);
  END LOOP;
END $$;

-- Media stays on disk keyed by content hash; the database stores paths and hashes.
CREATE TABLE raw.media (
  content_sha256 bytea       PRIMARY KEY,
  source_url     text        NOT NULL,
  storage_path   text        NOT NULL,
  mime_type      text,
  byte_size      integer,
  width          integer,
  height         integer,
  duration_s     integer,
  fetched_at     timestamptz NOT NULL DEFAULT now()
);
