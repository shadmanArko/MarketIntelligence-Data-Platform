# Market Intelligence Data Platform — conventions

Reusable data platform: collects public business, menu, social, web and search data for any vertical
and city, stores it in Postgres, and turns it into clean, versioned, ML-ready datasets. First market:
`berlin-food`; first tenant: `dhaka-kacchi`. The full plan is the PDF in this folder
("Market Intelligence Data Platform — Architecture & Build Plan").

**Scope:** data platform only — collect, clean, resolve, snapshot, publish marts and ML feature tables.
No LLM / agent / model-training code lives here. Free sources first; paid sources stay disabled in
config until there is a budget (see `docs/paid-sources.md`).

## Run it
```
docker compose up -d                       # Postgres 18 + PostGIS + pgvector + pg_trgm + h3 on :5434
uv sync
uv run mip db migrate                      # raw + ops schemas (migrations own these)
uv run mip discover -m berlin-food -s wolt # queue units of work
uv run mip fetch    -m berlin-food -s wolt -w 4   # resumable; rerun to continue
uv run mip status                          # queue, raw volumes, quarantine, drift
uv run mip transform                       # dbt build: staging -> core -> marts -> ml (+ tests)
uv run pytest -q
```

## Rules that must not be broken
1. **Raw is immutable.** Connectors store the complete response in `raw.payloads` (content-addressed by
   SHA-256) + one `raw.observations` row per fetch. Never update or delete raw. Everything after raw
   is rebuildable by dbt.
2. **Snapshots, not overwrites.** Moving numbers (ratings, prices, likes) are one row per observation.
3. **Idempotent tasks.** Raw rows, follow-up tasks and task completion commit in one transaction
   (`core/runner.py`). Task keys are deterministic.
4. **Gate 1 = Pydantic contract per entity type** (`contracts` on the connector). Failures go to
   `ops.quarantine`; new fields go to `ops.schema_drift`. Contracts use `extra="allow"` — never drop fields.
5. **Any parsing change bumps the connector `version`.**
6. **Missing is not zero.** NULL plus a reason; imputation only in the ml layer with indicator columns.
7. **Personal data minimised:** commenter / reviewer identities are salted-hashed (`MIP_HASH_SALT`),
   business accounts stored in full.
8. Times are `timestamptz` UTC; money `numeric(10,2)` + currency; geography PostGIS + H3 res 8.

## Layout
- `src/mip/core/` connector protocol, rate limiter, HTTP client (curl_cffi), queue, raw writer, runner
- `src/mip/connectors/<source>.py` one module per source, auto-registered via `@register`
- `src/mip/datasets/` bulk datasets (OSM, Overture, Foursquare, TripAdvisor, Zensus, ...) -> `raw.ds_*`
- `src/mip/resolution/` entity resolution (Splink) — owns `ops.business_assignment` (stable ids)
- `db/migrations/` raw + ops DDL; `dbt/` staging, core, marts, ml
- `config/markets/*.yaml`, `config/tenants/*.yaml`, `config/taxonomies/*.yaml`
- `data/` (git-ignored): bulk downloads, media by content hash, dev cache, logs

## Things learned the hard way
- Google throttles an IP after a few thousand fast Maps searches: keep `google_maps`/`serp` at ~1 req / 3 s.
- Wolt rate-limits per endpoint: separate lanes (`list`, `static`, `menu`, `dynamic`) keep one from starving others.
- Lieferando reviews API rejects `limit` > 30.
- Unsupervised EM over location blocks learns "same building = same business"; keep name m-values fixed and the
  cannot-link constraints in `resolution/listings.py`.
- Never solve CAPTCHAs or evade bot challenges; use the official-API slot instead and note it in docs/paid-sources.md.
- dbt untyped NULLs inside separate CTEs become `text`; union branches inline. Unnest JSON via `ops.jarr()`.

## Adding a source
New module in `src/mip/connectors/`, implement `discover`, `fetch`, `healthcheck`, give it `contracts`,
add it to the market YAML, add a fixture test in `tests/fixtures/<source>/`.
