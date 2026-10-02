-- Language detection results (computed in Python, joined by dbt): one row per text.
CREATE TABLE ops.text_language (
  text_kind   text        NOT NULL,         -- review | post | page | bio | menu_item
  text_id     text        NOT NULL,
  lang        text,                         -- ISO 639-1
  confidence  real,
  detector    text        NOT NULL,
  detected_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (text_kind, text_id)
);
