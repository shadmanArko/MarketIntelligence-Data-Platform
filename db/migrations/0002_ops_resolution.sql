-- Entity resolution bookkeeping: human labels, stable-id change log, social link review.
CREATE TABLE ops.match_review (
  pair_id        uuid        PRIMARY KEY DEFAULT uuidv7(),
  domain         text        NOT NULL DEFAULT 'listing'  -- listing | social | site
                 CHECK (domain IN ('listing', 'social', 'site')),
  left_id        text        NOT NULL,
  right_id       text        NOT NULL,
  match_prob     double precision,
  features       jsonb,
  label          boolean,                                 -- NULL = not reviewed yet
  labelled_by    text,
  labelled_at    timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (domain, left_id, right_id)
);

CREATE TABLE ops.entity_changes (
  change_id      uuid        PRIMARY KEY DEFAULT uuidv7(),
  resolution_run uuid        NOT NULL,
  kind           text        NOT NULL CHECK (kind IN ('create', 'merge', 'split', 'move', 'retire')),
  business_id    uuid        NOT NULL,
  other_business_id uuid,
  listing_id     text,
  detail         jsonb,
  changed_at     timestamptz NOT NULL DEFAULT now()
);

-- Stable id ledger: listing_key -> business_id, owned by the resolution job (not dbt),
-- because a business_id must survive re-runs.
CREATE TABLE ops.business_assignment (
  listing_key    text        PRIMARY KEY,              -- '<platform>:<platform id>'
  business_id    uuid        NOT NULL,
  match_prob     double precision,
  method         text        NOT NULL,                 -- splink | deterministic | manual | singleton
  assigned_at    timestamptz NOT NULL DEFAULT now(),
  resolution_run uuid        NOT NULL
);
CREATE INDEX ON ops.business_assignment (business_id);

CREATE TABLE ops.brand_assignment (
  business_id    uuid        PRIMARY KEY,
  brand_id       uuid        NOT NULL,
  brand_name     text        NOT NULL,
  assigned_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ops.social_assignment (
  account_key    text        PRIMARY KEY,              -- '<platform>:<handle or id>'
  business_id    uuid,
  score          double precision,
  decision       text        NOT NULL CHECK (decision IN ('auto', 'review', 'rejected', 'manual')),
  evidence       jsonb,
  assigned_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ops.resolution_runs (
  resolution_run uuid        PRIMARY KEY DEFAULT uuidv7(),
  started_at     timestamptz NOT NULL DEFAULT now(),
  ended_at       timestamptz,
  threshold      double precision,
  pairs_scored   bigint,
  clusters       bigint,
  precision_lab  double precision,
  recall_lab     double precision,
  model_json     jsonb
);
