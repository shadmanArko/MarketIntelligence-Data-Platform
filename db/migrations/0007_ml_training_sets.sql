-- Training-set registry: every exported set is traceable to its SQL, code version, cut-off and data versions.
CREATE SCHEMA IF NOT EXISTS ml;
CREATE TABLE ml.training_sets (
  training_set_id uuid        PRIMARY KEY DEFAULT uuidv7(),
  name            text        NOT NULL,
  version         integer     NOT NULL,
  as_of           timestamptz NOT NULL,
  source_model    text        NOT NULL,          -- e.g. ml.feature_business
  sql_hash        text        NOT NULL,          -- sha256 of the compiled model SQL
  git_commit      text,
  row_count       bigint      NOT NULL,
  feature_list    jsonb       NOT NULL,          -- [{name, type}]
  split           jsonb,                         -- how train/valid/test are cut (time + group)
  datasets        jsonb,                         -- ops.datasets versions in force
  path            text        NOT NULL,          -- Parquet folder
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, version)
);
