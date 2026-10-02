-- Mentions of businesses in page text (computed by `mip enrich mentions`, joined by dbt core.mention).
CREATE TABLE ops.text_mention (
  page_version_id uuid        NOT NULL,
  business_id     uuid        NOT NULL,
  matched_name    text        NOT NULL,
  char_offset     integer     NOT NULL,
  snippet         text,
  matcher         text        NOT NULL,
  detected_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (page_version_id, business_id)
);
