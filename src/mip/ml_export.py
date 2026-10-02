"""Versioned training-set exports: dbt builds the point-in-time feature model for a cut-off, DuckDB writes it to
Parquet (one folder per version), and ml.training_sets records exactly what produced it."""

import hashlib
import subprocess
from datetime import UTC, datetime

import duckdb
import orjson
from rich.console import Console

from mip.core.runs import git_commit
from mip.db import Jsonb, connect
from mip.settings import ROOT, settings

console = Console()

SETS = {
    # name: (dbt model, entity key, time column for splits, group column)
    "business_features": ("feature_business", "business_id", "as_of", "business_id"),
    "offering_features": ("feature_offering", "offering_id", "as_of", "business_id"),
}


def export(name: str, as_of: str | None = None) -> dict:
    model, key, time_col, group_col = SETS[name]
    cut = as_of or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    vars_arg = orjson.dumps({"as_of": cut}).decode()
    rc = subprocess.call(["dbt", "run", "--project-dir", str(ROOT / "dbt"), "--profiles-dir", str(ROOT / "dbt"),
                          "--select", model, "--vars", vars_arg, "-q"])
    if rc:
        raise SystemExit(f"dbt run failed for {model}")
    compiled = (ROOT / "dbt" / "target" / "run" / "mip" / "models" / "ml" / f"{model}.sql").read_text()
    sql_hash = hashlib.sha256(compiled.encode()).hexdigest()
    with connect() as c:
        version = c.execute("SELECT coalesce(max(version), 0) + 1 v FROM ml.training_sets WHERE name=%s",
                            (name,)).fetchone()["v"]
        datasets = c.execute("SELECT name, version FROM ops.datasets ORDER BY name").fetchall()
        cols = c.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='ml'"
                         " AND table_name=%s ORDER BY ordinal_position", (model,)).fetchall()
    out = settings().data_dir / "ml" / name / f"v{version:04d}"
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute(f"ATTACH '{settings().mip_database_url}' AS pg (TYPE postgres, READ_ONLY)")
    n = con.execute(f"SELECT count(*) FROM pg.ml.{model}").fetchone()[0]
    con.execute(f"COPY (SELECT * FROM pg.ml.{model} ORDER BY {key}) TO '{out}/data.parquet' "
                "(FORMAT parquet, COMPRESSION zstd)")
    features = [{"name": r["column_name"], "type": r["data_type"]} for r in cols]
    split = {"strategy": "time_then_group", "time_column": time_col, "group_column": group_col,
             "rule": "train on cut-offs before T, validate/test on later cut-offs; a group never spans splits"}
    (out / "manifest.json").write_bytes(orjson.dumps({
        "name": name, "version": version, "as_of": cut, "model": f"ml.{model}", "sql_hash": sql_hash,
        "git_commit": git_commit(), "rows": n, "features": features, "split": split,
        "datasets": [dict(d) for d in datasets]}, option=orjson.OPT_INDENT_2))
    (out / "model.sql").write_text(compiled)
    with connect() as c:
        c.execute("INSERT INTO ml.training_sets (name, version, as_of, source_model, sql_hash, git_commit, row_count,"
                  " feature_list, split, datasets, path) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (name, version, cut, f"ml.{model}", sql_hash, git_commit(), n, Jsonb(features),
                   split, {d["name"]: d["version"] for d in datasets}, str(out)))
    console.print(f"[green]{name} v{version}[/]: {n:,} rows as of {cut} -> {out}/data.parquet")
    return {"name": name, "version": version, "rows": n, "path": str(out)}
