# Market Intelligence Data Platform

Collects public business, menu, social, web and search data for a market (first: every Berlin restaurant),
stores it raw and immutable in Postgres, and turns it into clean, resolved, versioned, ML-ready datasets.
Built from *Market Intelligence Data Platform — Architecture & Build Plan* (the PDF in this folder).

## Quick start
```bash
docker compose up -d            # Postgres 18 + PostGIS + pgvector + pg_trgm + h3 on localhost:5434
uv sync && uv run playwright install chromium
uv run mip db migrate
./scripts/full_run.sh           # one complete Berlin run (resumable; rerun after any interruption)
uv run mip status               # queue, raw volumes, quarantine, schema drift
uv run mip report               # quality gates
```
Data lands in `data/` (bulk downloads, logs, ML exports) and in the `mip` database.

## Layers (one database, six schemas)
| Schema | Holds | Built by |
|---|---|---|
| `raw` | every response as received (content-addressed `payloads` + `observations`), bulk datasets `ds_*`, geography `geo_*` | connectors, loaders |
| `staging` | one typed, cleaned view per source × entity (gate 2 rules in `dbt/macros/cleaning.sql`) | dbt |
| `core` | `business`, `listing` (+ `_history` SCD2, `_snapshot`), `offering` (+ price snapshots, canonical dish), `coverage_observation`, `review`, `listing_cuisine`, `site`, `web_page`, `mention`, `social_account`, `post` (+ metrics), `area_stat` (H3 + LOR), `external_id`, `brand` | dbt (+ resolution job) |
| `marts` | `competitor_overview`, `menu_price_index`, `dish_market`, `area_demand`, `search_visibility`, `content_performance`, `trending_hashtags` | dbt |
| `ml` | point-in-time `feature_business`, `feature_offering`; `training_sets` registry | dbt + `mip ml export` |
| `ops` | runs, tasks (resumable queue), quarantine, schema drift, quality report, dataset registry, resolution ledger, review labels | platform |

## Sources
| Source | Route | State |
|---|---|---|
| Wolt | consumer API, H3 res-8 grid (1,351 points) → venue page, ordering conditions, full menu | running |
| Lieferando | postcode sweep (190) → menu CDN manifest/items/modifiers, fees, reviews (≤ 300 newest) | complete; reviews refetching |
| Google Maps | Maps web search, template replay, adaptive H3 7→9, 7 food terms | ~95 %, paced after Google throttled |
| OpenStreetMap | Geofabrik Berlin extract, every POI with all tags | loaded |
| Overture Maps | GeoParquet on S3 by bbox via DuckDB | loaded (2026-09-23.1) |
| Restaurant websites + Berlin food media | focused crawler, robots-aware, schema.org, socials, ordering providers | running |
| TikTok | yt-dlp public profiles + recent video detail | running |
| Instagram | Graph API Business Discovery + Hashtag Search | built; needs your token |
| Search | Google Maps local rankings for target keywords per district (free); organic via official APIs | local scheduled; organic needs a free key |
| Site popularity | CrUX rank buckets, 12 months, Germany | loaded |
| Census & geography | Zensus 2022 (17 variables, 100 m), LOR planning areas, postcodes, districts, Ortsteile, H3 | loaded |
| Calendar & weather | holidays, school holidays, Ramadan / Eid, Bengali dates, DWD daily weather | loaded |
| Wikidata | 6.8k dishes with de/en/bn/ur/ar/tr labels | loaded |

What still needs a key, payment or your decision: [docs/paid-sources.md](docs/paid-sources.md).

## The two hard problems
* **Entity resolution** ([ADR 0003](docs/adr/0003-entity-resolution.md)): deterministic links + Splink model +
  constrained clustering; stable ids with a change log. Label pairs with `uv run mip resolve review`;
  gate 2 = `uv run mip resolve evaluate` precision ≥ 0.95.
* **Point-in-time correctness** ([ADR 0006](docs/adr/0006-point-in-time-features.md)): every feature is computed
  "as of" a cut-off from snapshots observed before it; `uv run mip ml export business_features --as-of …`
  writes a registered, versioned Parquet set.

## Gates (from the plan)
| Gate | Check | How |
|---|---|---|
| 0 | test connector writes raw end to end, CI green | `pytest` (selftest connector), `.github/workflows/ci.yml` |
| 1 | master-list venues in core, quality report passes | `mip report` |
| 2 | ≥ 95 % precision on labelled pairs | `mip resolve review` → `mip resolve evaluate` (needs your ~200 labels) |
| 3 | integrity tests on core and marts | `mip transform` (dbt tests) |
| 5 | a model trains from the registered set without manual fixes | `mip ml export` → `data/ml/<name>/vNNNN/data.parquet` |
