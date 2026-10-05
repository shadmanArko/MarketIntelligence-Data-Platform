# Dhaka Kacchi Market Intelligence — the data

This is the guide to the data: what it is, where it lives, how it is organised, how much there is, how good it is,
and how to use it for analysis, machine learning and LLM agents. It is written for people and for LLMs. An agent
should read this file, then `docs/data/catalog.md` (or `catalog.json`) before writing a query.

- **What:** public data on Berlin's food market, collected, cleaned and linked into one Postgres database:
  restaurants on every platform, menus and prices, reviews, social-media posts, audiences, occasions and trends,
  plus Dhaka Kacchi's own social posts.
- **Size:** 22 GB in Postgres; about 2 million posts, 1.2 million menu items, 0.6 million reviews and 70,000
  businesses (counts as of 2026-10-04; `catalog.md` has the live numbers).
- **Freshness:** refreshed every Sunday at 01:00; YouTube searches daily at 10:00.
- **Scope:** the data platform only. No model or LLM code lives in this repository. Models and agents are separate
  projects that read from here.

---

## 1. Where the data is and how to connect

The database runs in Docker on this Mac. The container is `mip-postgres` (image `mip-postgres:18`: Postgres 18,
PostGIS, pgvector, h3, pg_trgm, unaccent). Its files are in the Docker volume
`marketintelligencedataplatform_mip-pgdata`.

| Setting | Value |
|---|---|
| Host / port | `localhost` / `5434` |
| Database | `mip` |
| Read-only user (use this for analysis, notebooks, BI, agents) | `mip_reader` / `mip_reader` |
| Owner (pipelines only) | `mip` / `mip` |
| URL | `postgresql://mip_reader:mip_reader@localhost:5434/mip` |

`mip_reader` can read `core`, `marts`, `ml`, `staging` and the `ops` registries (datasets, languages, tags, entity-resolution ids, runs). It cannot write: every transaction is read-only and
queries stop after 5 minutes. Tenant tables (`core.tenant_*`) return no rows unless the session sets
`SET app.tenant_id = 'dhaka-kacchi'`.

Docker Desktop must be running. Start the database with `docker compose up -d` in the project folder.

**DataGrip:** New → Data Source → PostgreSQL, using the values above. Starter queries are in `docs/explore.sql`.

**Terminal:** `psql postgresql://mip_reader:mip_reader@localhost:5434/mip`

**Python (pandas):**
```python
import pandas as pd, sqlalchemy as sa
eng = sa.create_engine("postgresql+psycopg://mip_reader:mip_reader@localhost:5434/mip")
df = pd.read_sql("select * from marts.occasion_content_calendar where day < current_date + 30", eng)
```

**DuckDB (fast analytics, also over the Parquet copies):**
```python
import duckdb
con = duckdb.connect(); con.sql("INSTALL postgres; LOAD postgres;")
con.sql("ATTACH 'postgresql://mip_reader:mip_reader@localhost:5434/mip' AS pg (TYPE postgres, READ_ONLY)")
con.sql("select platform, count(*) from pg.core.post group by 1").show()
```

**A copy on an external drive:** `uv run mip export snapshot --to "/Volumes/<drive>/dk-data"` (section 10).

---

## 2. How it is organised

```
sources ──► raw (immutable) ──► staging (views) ──► core (truth) ──► marts (answers) ──► ml (features + labels)
                                                         ▲
                       ops: queue, runs, quality gates, entity resolution, enrichment, registries
```

| Layer | What it holds | Rule |
|---|---|---|
| `raw` | Every response exactly as received: `raw.payloads` (JSON, content-addressed by SHA-256) and `raw.observations` (one row per fetch: source, entity, key, time, HTTP status). Bulk files load into versioned `raw.ds_<name>_<version>` tables. | Never updated or deleted. Everything else can be rebuilt from it. |
| `staging` | One view per source and entity: typed, cleaned, one row per raw record. | No business logic. |
| `core` | The joined truth: businesses, listings, menus, prices, reviews, posts, accounts, audiences, occasions, interest. | Moving numbers are snapshots (one row per observation), never overwritten. |
| `marts` | Decision-shaped tables: competitors, price index, demand per area, content performance, occasion calendar, trends. | Built only from `core`. |
| `ml` | Point-in-time feature tables with labels, exported as versioned Parquet. | No look-ahead: features use only what was known at `as_of`. |
| `ops` | Work queue, runs, quarantine, schema drift, entity-resolution ids, language and tag outputs, registries. | Operational; read `ops.datasets` and `ml.training_sets` for lineage. |

Conventions everywhere:
- **Times** are `timestamptz` in UTC. Marts that show local time use Europe/Berlin and say so in the column name.
- **Money** is `numeric(10,2)` in EUR.
- **Geography** uses PostGIS (`geography` point, WGS84), Uber H3 cells at resolution 8 (`h3_r8`, about 0.7 km²), and
  Berlin LOR codes: 2-digit district, 8-digit planning area (542 areas).
- **Missing is not zero.** NULL means unknown or not provided. Counts of 0 are real zeros. Imputation happens only
  in `ml` tables, next to an indicator column.
- **Personal data** is minimised. Reviewer, commenter and Reddit author identities are salted hashes (`h:…`).
  Business accounts are stored in full.

---

## 3. What is in it

Rows are as of 2026-10-04. Live counts are in `docs/data/catalog.md`.

### 3.1 Businesses and listings (who is in the market)

| Table | Rows | Grain |
|---|---:|---|
| `core.business` | 69,673 (65,215 in Berlin, 7,910 closed) | one real-world business across all platforms |
| `core.listing` | 127,318 | one business on one platform (Foursquare 48,172 · Overture 29,337 · Google Maps 18,448 · OSM 14,476 · TripAdvisor 7,559 · Wolt 4,792 · Lieferando 4,534) |
| `core.listing_snapshot` | 107,803 | listing × observation: rating, review count, fees, minimum order, open or closed |
| `core.listing_history` | 149,731 | SCD type 2: a new row when name, address, contact or brand changes |
| `core.listing_cuisine` | 137,165 | listing × unified cuisine |
| `core.coverage_observation` | 1.41 M | listing × delivery area (H3 or postcode) × observation: delivers there, fee, ETA |
| `core.brand` | 1,862 | chains |
| `core.external_id`, `core.site`, `core.web_page` | 146k / 20k / 79k | outside identifiers, websites, crawled page versions |

Entity resolution: Splink plus deterministic rules and constraints (`src/mip/resolution/`). On 210 hand-labelled
pairs it scores precision 1.00 and recall 0.93. `business_id` is stable across re-runs (`ops.business_assignment`).

### 3.2 Menus and prices

| Table | Rows | Grain |
|---|---:|---|
| `core.offering` | 1.21 M | menu item on a listing: name, description, category, canonical `dish_id`, dietary flags |
| `core.offering_price_snapshot` | 2.39 M | item × observation: price, original price, discount. Outliers are flagged with `outlier_reason`, never deleted. |
| `marts.menu_price_index` / `marts.dish_market` | – | item price against the Berlin median for its dish; per-dish market size and median price |

### 3.3 Reviews

`core.review`: 587,016 Lieferando reviews (236,194 with text) with rating, date and hashed reviewer. Language of
each text is in `core.review_language` and `ops.text_language`. Google review text is not collected (paid only).

### 3.4 Social content and performance

| Table | Rows | Grain |
|---|---:|---|
| `core.post` | 1.96 M (Reddit 1.53 M · TikTok 246k · YouTube 181k) | one post or video: title, caption, format, duration, hashtags, `context` (account, channel or subreddit) |
| `core.post_metrics_snapshot` | 2.12 M | post × observation: views, likes (Reddit: score), comments, shares, saves, post age |
| `core.content_tag` | 1.61 M | post × tag: `dish`, `community`, `occasion`, `cue` (format or angle), `rice_dish` (Wikidata) |
| `ops.text_language` | 2.26 M | detected language of posts, reviews and pages, with confidence |
| `core.social_account`, `core.social_account_snapshot` | 7,628 / 2,601 | accounts and follower counts |
| `core.tenant_social_post`, `core.tenant_social_metrics_snapshot` | 417 / 417 | Dhaka Kacchi's own Instagram, Facebook and Threads posts with reach, saves and shares (row-level security) |
| `marts.tenant_content_performance` | 417 | own posts with latest metrics, tags, language, engagement rate and percentile within the account (RLS). Sources: the warehouse connector and delivered XLSX exports (`raw.ds_first_party_social_export_*`). Instagram reports no impressions, Threads no reach, and only Facebook reports clicks: those are NULL, not 0. |
| `marts.content_performance` | – | each post scored against its own peer group: `perf_pct_in_peer`, `perf_lift_vs_peer`, `is_viral_in_peer` |
| `marts.content_feature_performance` | – | per platform × tag: mean lift against the platform baseline, with standard error |
| `marts.posting_time_performance` | – | platform × format × weekday × Berlin hour |
| `marts.topic_trends_weekly`, `marts.trending_hashtags` | – | topic momentum: last 4 weeks against the 12 before |

Sources:
- **Reddit:** 30 subreddits since 2019 via the Arctic Shift archive. Scores are the archive's second reading, about
  36 hours after posting.
- **TikTok:** public profiles of 2,528 Berlin restaurants and food creators.
- **YouTube:** Data API: 229 searches, plus channels and their uploads.
- **Instagram:** waits for Meta App Review. 4,733 accounts are queued.

### 3.5 Audiences and geography

| Table | Rows | Grain |
|---|---:|---|
| `core.community`, `core.community_country`, `core.community_dish`, `core.community_greeting` | 38 / 92 / 107 / 129 | Berlin communities that eat meat with rice: languages, scripts, their own dishes, greetings in native script |
| `core.community_audience` | 21,616 | half-year × community × area (Berlin, district, LOR): residents and share (official statistics) |
| `core.area_stat`, `core.area_stat_lor` | 60k / 32k | Zensus 2022 per H3 cell or LOR: population, age, household size, foreigner share, rent and more |
| `marts.area_demand` | – | per H3 cell: residents, businesses, South Asian and halal supply, residents per South Asian venue |

### 3.6 Occasions, calendar and weather

| Table | Grain |
|---|---|
| `core.occasion_day` (25k) | day × community × occasion, 2015–2030: holiday names (English and native), food role, tone, how many days ahead to start content, greeting, Ramadan iftar and suhoor times |
| `marts.occasion_content_calendar` | next 15 months: occasion, community, greeting, dishes to bridge to, Berlin community size, top districts, Berlin events that day |
| bulk tables `calendar_berlin`, `dwd_daily_berlin_tempelhof` | public and school holidays, Islamic dates, daily weather since 2015 |

Islamic dates are calculated and can be ±1 day. Communities that follow moon sighting (Bangladeshi, Indian,
Nigerian) are shifted by +1 day.

### 3.7 Interest and long-run trends

- `core.interest_daily` (407k): daily Wikipedia page views since 2015 for 100+ dishes and occasions in 27 languages.
- `core.osm_poi_history` (21,837): when food places appeared on and disappeared from OpenStreetMap since 2010.
- `marts.cuisine_supply_monthly`, `marts.dish_interest_weekly`, `marts.survival_since_2021`.

### 3.8 Search and web

`marts.search_visibility` (Google local results for 714 queries), `core.mention` (businesses named on food-media
pages), and `core.site` / `core.web_page` (restaurant websites).

---

## 4. Keys: how tables join

| Key | Meaning | Where |
|---|---|---|
| `business_id` (uuid) | one real business; stable | business, listing (via `ops.business_assignment`), feature_business, competitor_overview |
| `listing_id` / `listing_key` (`platform:id`) | one platform record | listing*, offering, review, coverage_observation |
| `offering_id` | one menu item on one listing | offering, offering_price_snapshot, feature_offering |
| `post_id` = md5(`platform:post_platform_id`) | one post or video | post, post_metrics_snapshot, content_tag, content_performance, feature_content |
| `account_id` = md5(`platform:handle`) | one social account | social_account*, post |
| `h3_r8` | H3 resolution-8 cell | area_stat, area_demand, business_geo |
| `area_code` / LOR code | `11` = Berlin, 2-digit district, 8-digit planning area | community_audience, area_stat_lor |
| `community_id` | e.g. `bangladeshi`, `turkish`, `syrian`; `all` = everyone | community*, occasion_day, content_tag (`tag_type='community'`) |
| `occasion_type` | e.g. `eid_al_fitr`, `nowruz`, `diwali`, `ramadan_period` | occasion_day, occasion_type, content_tag (`tag_type='occasion'`) |
| `dish_id`, `cuisine_id` | canonical dish and cuisine | offering, dish_market, listing_cuisine, content_tag |
| `day` / `observed_at` / `posted_at` | dates and times (UTC) | everywhere |

---

## 5. Time: snapshots and point-in-time

- Anything that moves (ratings, prices, fees, views, likes) is one row per observation in a `*_snapshot` table.
  "Current" means the latest row per key.
- Weekly refreshes add a new observation each Sunday. History therefore grows: price and rating time series start
  in September 2026, and post histories go back to 2018–2019 through their publish dates.
- The `ml` models take a dbt variable `as_of`. Every feature is computed from data observed at or before that time,
  so a training row never sees the future.

---

## 6. Quality: what has been checked, and what to be careful with

Checks:
- **Gate 1:** every raw record is validated against a Pydantic contract. Failures go to `ops.quarantine`; new or
  missing fields go to `ops.schema_drift`.
- **Gate 2:** entity resolution is evaluated on hand labels (precision 1.00, recall 0.93).
- **dbt tests:** uniqueness, not-null, accepted values, ranges, relationships and minimum row counts on core, marts
  and ml. Run with `uv run mip transform`.
- **Quality report:** coverage, freshness and null rates per source in `ops.quality_report` (`uv run mip report`).

Known limits and biases (read before modelling):
- **Instagram is missing** until Meta approves access. **Google review text, X and LinkedIn are not collected.**
- **Reddit** scores are early (about 36 hours) and English and German dominate. Subreddit choice shapes the sample.
- **TikTok and YouTube metrics** are cumulative at observation time. Compare posts of similar age (`post_age_hours`)
  or use the peer-normalised labels.
- **Peer normalisation** compares each post with its own account or subreddit. The labels measure relative
  success, not absolute reach.
- **Tags** come from dictionaries: precise on dish and occasion names, looser on generic cues such as "hot" and
  "neu". Language detection is unreliable on very short texts, so filter `confidence >= 0.6`.
- **Population statistics** count citizens. Second-generation Germans appear only in the migration-background
  figures, which exist for 24 origin areas.
- **Associations are not causes.** The marts show what goes together with performance, not what causes it.

---

## 7. Machine learning

Training sets are exported as versioned Parquet with a manifest and the exact SQL used, and registered in
`ml.training_sets` (name, version, `as_of`, row count, feature list, split rule, dataset versions, git commit).

| Training set | Rows (latest) | One row = | Labels | Typical use |
|---|---:|---|---|---|
| `content_features` | 1.87 M | a mature post (Reddit, TikTok, YouTube) | `label_log_perf`, `label_lift_vs_prior` (against the peer's earlier posts), `label_pct_in_peer`, `label_viral_in_peer` | which content, format, language, occasion and timing performs |
| `offering_features` | 1.17 M | a menu item | price, `dish_id`, dietary flags | price suggestion, dish classification |
| `business_features` | 65k | a Berlin business | rating, survival / closed, review volume | competitor scoring, survival, demand |

```python
import pandas as pd
df = pd.read_parquet("data/ml/content_features/v0003/data.parquet")   # path in ml.training_sets.path
```

Rules that keep models honest:
- **Split by time, then by group.** Train on earlier `posted_at` or `as_of`, test on later. Keep one account
  (`peer_group`) or one business entirely within a single split. The rule is stored in `ml.training_sets.split`.
- **Do not use `label_*` columns, or `likes` / `views` / `comments`, as features** for a model that predicts
  performance. They are outcomes.
- Weight or stratify by platform: Reddit is 78% of the content rows.
- Re-export after each weekly refresh (`uv run mip ml export content_features`). Versions are immutable.

The best label is your own orders. When the read-only order data from the Dhaka Kacchi warehouse is connected, it
lands in `raw` as `own_order` and can become the target that turns "views" into "sales".

---

## 8. LLMs and agents

Suggested setup for an agent that answers business questions from this data:
1. **Connect as `mip_reader`.** It is read-only and times out after 5 minutes, so the agent cannot damage anything.
2. **Give the agent this file and `docs/data/catalog.json` as context.** The catalog has every table, its columns,
   their meaning and an example row.
3. **Prefer `marts`, then `core`.** Avoid `raw`: it is JSON and large. `staging` is for debugging.
4. **Useful tools to give an agent:** `run_sql(query)` with a row limit; `describe_table(name)` backed by the
   catalog; `next_occasions(days)` = `marts.occasion_content_calendar`; `competitors_near(lat, lon)` =
   `marts.competitor_overview`; `what_works(platform)` = `marts.content_feature_performance`.
5. **Guardrails:** never join hashed reviewer or author ids to outside data. Tenant tables need
   `SET app.tenant_id`. Prefer aggregates over row dumps.

Example questions and where the answer is:

| Question | Query |
|---|---|
| What should we post in the next two weeks, for whom, in which language? | `select day, community, occasion_type, greeting, bridge_dishes from marts.occasion_content_calendar where day < current_date + 14 order by day` |
| What content works on TikTok? | `select tag_type, tag_id, posts, mean_lift_vs_platform from marts.content_feature_performance where platform='tiktok' and posts >= 150 order by 4 desc` |
| Who sells biryani and at what price? | `select * from marts.dish_market where dish_id like '%biryani%'` |
| Where are South Asian restaurants scarce? | `select h3_r8, population, residents_per_south_asian_venue from marts.area_demand order by 3 desc nulls last limit 20` |
| How many Turkish Berliners live in each district? | `select area_code, residents from core.community_audience where community_id='turkish' and level='district_mh' and reference_date=(select max(reference_date) from core.community_audience)` |
| Is interest in Nowruz rising? | `select * from core.interest_daily where topic ilike '%nowruz%' order by day desc limit 60` |

For retrieval-augmented setups, good text to embed is `core.review.text`, `core.post.title || caption`,
`core.offering.name || description` and `core.web_page.main_text`, each kept with its key and date. pgvector is
installed, so embeddings can live next to the data.

---

## 9. Refresh, lineage and rebuilding

| What | When | How |
|---|---|---|
| Weekly refresh: Wolt, Lieferando, own posts, Wikipedia, Reddit (last 3 months), YouTube statistics, Berlin events, then rebuild, tests, report and training sets | Sundays 01:00 | `scripts/weekly_refresh.sh` (launchd `com.dhakakacchi.mip.weekly`) |
| YouTube searches (about 90 a day, free quota) | daily 10:00 | `scripts/daily_youtube.sh` |
| Rebuild everything from raw | on demand | `uv run mip transform` |
| Regenerate the catalog | on demand | `uv run mip docs catalog` |
| Check progress | any time | `uv run mip status`; logs in `data/logs/`; `ops.runs`, `ops.tasks` |

Lineage: `ops.runs` records every collection run (git commit, config hash, metrics). Each raw observation names its
run and connector version. `ops.datasets` lists every bulk dataset version and licence. `ml.training_sets` lists
which dataset versions and SQL produced each training set.

---

## 10. Copy and backup

```bash
uv run mip export snapshot --to "/Volumes/<your drive>/dk-data"
```

This creates `mip-snapshot-YYYYMMDD/` with:

| Path | Content |
|---|---|
| `database/mip.dump` | the full Postgres backup, raw included; restore with `pg_restore` |
| `parquet/<schema>/<table>.parquet` | every core, marts and ml table, readable without a database |
| `training_sets/` | all training-set versions |
| `docs/` | this guide, the catalog, configs and taxonomies |
| `manifest.json` | row counts, file sizes, checksums |
| `README.md` | how to open or restore it |

Plan for about 10–15 GB. `--no-dump` gives a smaller, Parquet-only copy.

---

## 11. Sources, licences and privacy

- **Collection rules:** public pages and official APIs only. No logins to other people's accounts, no private
  groups, no CAPTCHA or bot-challenge workarounds. robots.txt is respected for crawling.
- **Licences:** open datasets keep their licences, recorded in `ops.datasets.terms`. Examples: OSM (ODbL),
  Overture (CDLA / ODbL), Zensus and Amt für Statistik (dl-de/by-2-0), Wikidata (CC0), Wikipedia page views
  (CC0 / CC BY-SA), Foursquare OS Places (Apache 2.0), DWD (CC BY 4.0).
- **Platform data** (Wolt, Lieferando, Google Maps, TikTok, YouTube, Reddit) is for internal market research.
  Check each platform's terms before republishing raw content.
- **Personal data:** reviewer, commenter and author identities are salted hashes. Keep `MIP_HASH_SALT` secret and
  do not try to re-identify people.

More detail: `docs/social-content-data.md` (content sources), `docs/paid-sources.md` (what needs keys or money),
`docs/adr/` (design decisions), `config/taxonomies/` (communities, occasions, cuisines and dishes).

## Glossary

- **Lift:** ln((performance + 1) / (peer median + 1)). +0.40 ≈ 1.5× usual; −0.25 ≈ 0.78×.
- **Peer group:** the account, channel or subreddit a post is compared with.
- **Mature post:** old enough for stable numbers (72 h; Reddit 24 h).
- **LOR:** Berlin's official planning geography (Lebensweltlich orientierte Räume).
- **H3 r8:** hexagonal grid cell of about 0.7 km².
- **SCD2:** keeping history by adding a row whenever attributes change.
- **as_of:** the point in time a feature row describes.
