-- One row per import of raw data from the VPS collector (light daily API sources run 24/7 on the VPS).
CREATE TABLE ops.collector_import (
  import_id        uuid        PRIMARY KEY DEFAULT uuidv7(),
  started_at       timestamptz NOT NULL DEFAULT now(),
  ended_at         timestamptz,
  from_fetched_at  timestamptz,
  to_fetched_at    timestamptz,
  runs             integer     NOT NULL DEFAULT 0,
  payloads         integer     NOT NULL DEFAULT 0,
  observations     integer     NOT NULL DEFAULT 0,
  sources          text[]      NOT NULL DEFAULT '{}',
  status           text        NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
  error            text
);
