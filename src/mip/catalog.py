"""Data catalog generator: every table and view in the warehouse, with what it is, its grain, row count, size,
columns (type + meaning) and one example row. Written for humans and for LLMs / agents that need to understand the
data before querying it. Descriptions come from the dbt manifest (schema YAML + the comment header of each model's
SQL) and from the raw / ops registries; numbers are read live from Postgres.

    uv run mip docs catalog          ->  docs/data/catalog.md  +  docs/data/catalog.json
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from mip.db import connect
from mip.settings import ROOT

console = Console()
OUT = ROOT / "docs" / "data"
SCHEMAS = ("core", "marts", "ml", "staging", "ops", "raw")
SCHEMA_ROLE = {
    "raw": "Immutable landing zone: every API / page response exactly as received (content-addressed JSON) plus "
           "versioned bulk datasets (raw.ds_*). Never updated; everything else is rebuilt from here.",
    "staging": "Views: one per source and entity, typed and cleaned (text normalised, money parsed, ids extracted). "
               "1:1 with raw records; no business logic.",
    "core": "The clean, joined truth: businesses (entity-resolved across platforms), listings, menus, prices, "
            "reviews, posts, audiences, occasions. Snapshots for anything that moves.",
    "marts": "Answer-shaped tables for decisions and dashboards (competitors, prices, demand, content performance, "
             "occasion calendar, trends).",
    "ml": "Point-in-time feature tables with labels, ready for model training; exported as versioned Parquet.",
    "ops": "Operations: work queue, runs, data-quality quarantine and drift, entity-resolution assignments, "
           "enrichment outputs (language, tags, mentions), dataset and training-set registries.",
}
OPS_DOC = {
    "tasks": "Work queue: one row per unit of collection work (source, entity, natural key, status, attempts).",
    "runs": "One row per CLI run (discover / fetch / transform / export) with metrics and errors.",
    "quarantine": "Records that failed their Pydantic contract (gate 1), with the validation error.",
    "schema_drift": "New or missing fields seen in source payloads compared with the baseline.",
    "business_assignment": "Stable business_id per listing (entity resolution output; ids survive re-runs).",
    "brand_assignment": "Chain / brand membership of businesses.",
    "entity_changes": "Log of merges and splits of businesses between resolution runs.",
    "match_review": "Hand labels for entity-resolution pairs (gate 2 evaluation).",
    "text_language": "Detected language per text (review, page, post, comment) with confidence.",
    "text_mention": "Business mentions found in media / blog pages.",
    "content_tag": "Dish / community / occasion / format-cue tags per post (dictionary matcher).",
    "datasets": "Registry of bulk datasets: name, version, source URL, licence, raw table, checksum.",
    "migrations": "Applied database migrations.",
}
EXTRA_DOC = {
    "ops.connector_health": "Healthcheck results per source over time (ok, detail, latency).",
    "ops.quality_report": "Data-quality report per run: coverage, freshness, null rates, test results.",
    "ops.resolution_runs": "One row per entity-resolution run with parameters and evaluation metrics.",
    "ops.schema_known_fields": "Baseline of known payload fields per source / entity (schema-drift detection).",
    "ops.social_assignment": "Social account -> business link chosen by `mip resolve social`, with score.",
    "ml.training_sets": "Registry of exported training sets: name, version, rows, features, label, Parquet path.",
    "core.community": "Berlin audience communities (seed from config/taxonomies/communities.yaml): languages, "
                      "scripts, religion mix, statistics labels.",
    "core.community_country": "Community -> ISO country codes (drives the holiday calendar).",
    "core.community_dish": "Each community's own meat-and-rice dishes (native name, transliteration, English).",
    "core.community_greeting": "Greeting per community and occasion type in native script + transliteration.",
    "core.content_priors": "Published platform rules and benchmarks (algorithm signals, formats, times, what to "
                           "avoid) with source URL and evidence strength — research of 2026-10.",
    "core.cuisine_map": "Platform cuisine tag -> unified cuisine id and group (seed from food_delivery.yaml).",
    "core.dish_map": "Menu-item name pattern -> canonical dish id (seed from food_delivery.yaml).",
    "core.occasion_type": "Occasion types: food role, tone, lead days, holiday-name regex (seed).",
    "core.social_account_snapshot": "Social account x observation: followers, following, post count.",
    "core.tenant_social_post": "Dhaka Kacchi's own posts (Instagram, Facebook, Threads) from the first-party "
                               "warehouse. Row-level security by tenant_id.",
    "core.tenant_social_metrics_snapshot": "Own post x capture time: impressions, reach, likes, comments, shares, "
                                           "saves, clicks. Row-level security by tenant_id.",
}
SKIP_SAMPLE = {"raw.payloads", "raw.observations"}


def _manifest() -> dict:
    p = ROOT / "dbt" / "target" / "manifest.json"
    if not p.exists():
        return {}
    m = json.loads(p.read_text())
    out = {}
    for node in m.get("nodes", {}).values():
        if node.get("resource_type") not in ("model", "seed"):
            continue
        header = []
        for line in (node.get("raw_code") or "").splitlines():
            s = line.strip()
            if s.startswith("{{") or s.startswith("{%") or s.endswith("}}") and not s.startswith("--"):
                continue
            if s.startswith("--"):
                header.append(s[2:].strip())
            elif s and not s.startswith("{#"):
                break
        cols = {c: (v.get("description") or "") for c, v in node.get("columns", {}).items()}
        for h in header:   # "--   col_name   meaning" lines in the header document columns
            mm = re.match(r"^([a-z_][a-z0-9_]*)\s{2,}(.+)$", h)
            if mm and not cols.get(mm.group(1)):
                cols[mm.group(1)] = mm.group(2)
        out[f"{node['schema']}.{node['name']}"] = {
            "description": node.get("description") or " ".join(h for h in header if h),
            "columns": cols, "file": node.get("original_file_path"), "materialized": node["config"].get("materialized"),
        }
    return out


def _short(v) -> str:
    s = "NULL" if v is None else str(v)
    s = s.replace("\n", " ").replace("|", "/")
    return s[:70] + "…" if len(s) > 70 else s


def build_catalog() -> dict:
    man = _manifest()
    cat = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "database": "mip", "schemas": {}}
    with connect() as c:
        c.execute("set statement_timeout = '10min'")
        rels = c.execute("""
            select n.nspname as schema, c.relname as name, c.relkind as kind,
                   pg_total_relation_size(c.oid) as bytes, c.reltuples::bigint as est_rows
            from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = any(%s) and c.relkind in ('r', 'v', 'm', 'p') and not c.relispartition
            order by 1, 2""", (list(SCHEMAS),)).fetchall()
        cols = c.execute("""
            select table_schema, table_name, column_name, data_type, udt_name from information_schema.columns
            where table_schema = any(%s) order by table_schema, table_name, ordinal_position""",
                         (list(SCHEMAS),)).fetchall()
        datasets = {r["raw_table"]: r for r in c.execute(
            "select name, version, raw_table, source_url, terms, loaded_at from ops.datasets").fetchall()}
        colmap: dict = {}
        for r in cols:
            colmap.setdefault(f"{r['table_schema']}.{r['table_name']}", []).append(r)
        for rel in rels:
            fq = f"{rel['schema']}.{rel['name']}"
            if rel["schema"] == "raw" and rel["name"].startswith("ds_") and fq not in datasets:
                continue        # superseded dataset versions: the registry points at the current one
            info = man.get(fq, {})
            if rel["kind"] == "v":
                rows = None     # views are not counted (they read raw on demand)
            elif rel["est_rows"] > 3_000_000 or fq in SKIP_SAMPLE:
                rows = int(rel["est_rows"]) if rel["est_rows"] >= 0 else None
                if rel["kind"] == "p":
                    rows = c.execute(f"select sum(c.reltuples)::bigint n from pg_inherits i join pg_class c on "
                                     f"c.oid = i.inhrelid where i.inhparent = '{fq}'::regclass").fetchone()["n"]
            else:
                rows = c.execute(f'select count(*) n from {rel["schema"]}."{rel["name"]}"').fetchone()["n"]
            sample = None
            if rel["kind"] != "v" and fq not in SKIP_SAMPLE and rel["schema"] != "raw" and rows:
                try:
                    r = c.execute(f'select * from {rel["schema"]}."{rel["name"]}" limit 1').fetchone()
                    sample = {k: _short(v) for k, v in (r or {}).items()}
                except Exception:
                    c.rollback()
            desc = info.get("description") or EXTRA_DOC.get(fq, "")
            if rel["schema"] == "ops":
                desc = desc or OPS_DOC.get(rel["name"], "")
            if fq in datasets:
                d = datasets[fq]
                desc = desc or f"Bulk dataset `{d['name']}` version {d['version']} from {d['source_url']} ({d['terms']})."
            table = {"kind": {"r": "table", "v": "view", "m": "materialized view", "p": "partitioned table"}[rel["kind"]],
                     "rows": rows, "bytes": int(rel["bytes"]), "description": desc, "dbt_file": info.get("file"),
                     "columns": [{"name": col["column_name"], "type": col["udt_name"],
                                  "description": info.get("columns", {}).get(col["column_name"], "")}
                                 for col in colmap.get(fq, [])],
                     "example_row": sample}
            cat["schemas"].setdefault(rel["schema"], {})[rel["name"]] = table
        cat["raw_observations_by_source"] = [dict(r) for r in c.execute("""
            select source, entity_type, count(*) as observations, min(fetched_at)::date as first_fetch,
                   max(fetched_at)::date as last_fetch
            from raw.observations group by 1, 2 order by 1, 2""").fetchall()]
    return cat


def _fmt_rows(n) -> str:
    return "view" if n is None else f"{n:,}"


def _fmt_bytes(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def write_catalog() -> Path:
    cat = build_catalog()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "catalog.json").write_text(json.dumps(cat, indent=1, default=str, ensure_ascii=False))
    L = ["# Data catalog (generated)", "",
         f"Generated {cat['generated_at']} by `uv run mip docs catalog` from the live database `mip`. "
         "Read `docs/DATA.md` first for how the pieces fit together; this file lists every table.", ""]
    L += ["## Contents", ""]
    for sch in SCHEMAS:
        tabs = cat["schemas"].get(sch, {})
        size = sum(t["bytes"] for t in tabs.values())
        L.append(f"- [`{sch}`](#schema-{sch}) — {len(tabs)} tables/views, {_fmt_bytes(size)}")
    L.append("")
    for sch in SCHEMAS:
        tabs = cat["schemas"].get(sch, {})
        L += [f"## Schema `{sch}`", "", SCHEMA_ROLE[sch], "", "| Table | Kind | Rows | Size | What it is |",
              "|---|---|---:|---:|---|"]
        for name, t in tabs.items():
            L.append(f"| `{sch}.{name}` | {t['kind']} | {_fmt_rows(t['rows'])} | {_fmt_bytes(t['bytes'])} | "
                     f"{(t['description'] or '').replace('|', '/')[:180]} |")
        L.append("")
        if sch == "raw":
            L += ["### Raw observations by source", "", "| Source | Entity | Observations | First | Last |",
                  "|---|---|---:|---|---|"]
            for r in cat["raw_observations_by_source"]:
                L.append(f"| {r['source']} | {r['entity_type']} | {r['observations']:,} | {r['first_fetch']} | "
                         f"{r['last_fetch']} |")
            L.append("")
            continue
        if sch == "staging":
            continue    # staging columns mirror core; see the dbt SQL files for details
        for name, t in tabs.items():
            L += [f"### `{sch}.{name}`", "", t["description"] or "_(no description)_", "",
                  f"Rows: **{_fmt_rows(t['rows'])}** · size {_fmt_bytes(t['bytes'])}"
                  + (f" · defined in `dbt/{t['dbt_file']}`" if t["dbt_file"] else ""), "",
                  "| Column | Type | Meaning | Example |", "|---|---|---|---|"]
            ex = t["example_row"] or {}
            for col in t["columns"]:
                L.append(f"| `{col['name']}` | {col['type']} | {(col['description'] or '').replace('|', '/')} | "
                         f"{ex.get(col['name'], '') if ex else ''} |")
            L.append("")
    (OUT / "catalog.md").write_text("\n".join(L))
    console.print(f"[green]catalog[/]: {sum(len(v) for v in cat['schemas'].values())} tables -> {OUT / 'catalog.md'}")
    return OUT / "catalog.md"
