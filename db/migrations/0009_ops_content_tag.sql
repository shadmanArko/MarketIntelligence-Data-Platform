-- Content tags per post / video / comment (computed by `mip enrich content`, joined by dbt): dishes, communities,
-- occasions, format cues. Deterministic dictionary matching; matcher version recorded.
CREATE TABLE ops.content_tag (
  text_kind  text        NOT NULL,          -- post | comment
  text_id    text        NOT NULL,
  tag_type   text        NOT NULL,          -- dish | community | occasion | cue | rice_dish
  tag_id     text        NOT NULL,
  matched    text,
  matcher    text        NOT NULL,
  tagged_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (text_kind, text_id, tag_type, tag_id)
);
CREATE INDEX content_tag_tag ON ops.content_tag (tag_type, tag_id);
