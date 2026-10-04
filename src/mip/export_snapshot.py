"""Portable copy of the whole platform for an external drive / another machine / an ML or agent project.

    uv run mip export snapshot --to "/Volumes/MyDrive/dhaka-kacchi-data"

Writes <to>/mip-snapshot-YYYYMMDD/ with:
  database/mip.dump        full Postgres backup (pg_dump custom format, compressed): restores everything, raw included
  parquet/<schema>/<table>.parquet   core, marts, ml (+ small ops registries): open with pandas / polars / DuckDB /
                                      Spark without any database
  training_sets/           the versioned ML exports (data/ml)
  docs/                    DATA.md, data catalog (md + json), source / credential guides, config taxonomies
  manifest.json            what is inside: row counts, file sizes, sha256, git commit, created_at
  README.md                how to restore / open it
"""

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from rich.console import Console

from mip.db import connect
from mip.settings import ROOT, settings

console = Console()
PARQUET_SCHEMAS = ("core", "marts", "ml")
OPS_TABLES = ("datasets", "business_assignment", "brand_assignment", "social_assignment", "text_language",
              "content_tag", "quality_report", "runs")
CONTAINER = "mip-postgres"

README = """# Dhaka Kacchi market-intelligence data snapshot

Created {created} from git commit `{commit}`. Start with `docs/DATA.md` (what the data is, how it is organised,
how to use it for analysis, ML and agents); `docs/data/catalog.md` lists every table with rows and columns.

## Option A — open the Parquet files (no database needed)

```python
import duckdb
con = duckdb.connect()
con.sql("select platform, count(*) from 'parquet/core/post.parquet' group by 1").show()
```
pandas: `pd.read_parquet("parquet/marts/occasion_content_calendar.parquet")`; polars: `pl.read_parquet(...)`.

## Option B — restore the full database (everything, including raw)

Needs Docker. From the project repository (or any Postgres 18 with PostGIS, pgvector, h3, pg_trgm, unaccent):

```bash
docker compose up -d
docker exec -i mip-postgres pg_restore -U mip -d mip --clean --if-exists --no-owner < database/mip.dump
```
Connection afterwards: host localhost, port 5434, database `mip`, user `mip_reader` / password `mip_reader`
(read-only) or `mip` / `mip` (owner).
"""


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(to: Path, dump: bool = True, parquet: bool = True) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    out = Path(to).expanduser() / f"mip-snapshot-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    manifest: dict = {"created_at": datetime.now(UTC).isoformat(timespec="seconds"), "git_commit": commit,
                      "files": {}, "tables": {}}

    # docs first (small, always useful)
    from mip.catalog import write_catalog
    write_catalog()
    docs = out / "docs"
    docs.mkdir(exist_ok=True)
    for rel in ("docs/DATA.md", "docs/social-content-data.md", "docs/paid-sources.md", "README.md", "CLAUDE.md"):
        if (ROOT / rel).exists():
            shutil.copy2(ROOT / rel, docs / Path(rel).name)
    shutil.copytree(ROOT / "docs" / "data", docs / "data", dirs_exist_ok=True)
    shutil.copytree(ROOT / "config", docs / "config", dirs_exist_ok=True)
    shutil.copytree(ROOT / "docs" / "adr", docs / "adr", dirs_exist_ok=True)

    if parquet:
        con = duckdb.connect()
        con.execute("INSTALL postgres; LOAD postgres;")
        con.execute(f"ATTACH '{settings().mip_database_url}' AS pg (TYPE postgres, READ_ONLY)")
        with connect() as c:
            tables = [(r["s"], r["t"]) for r in c.execute(
                "select table_schema s, table_name t from information_schema.tables where table_type = 'BASE TABLE'"
                " and (table_schema = any(%s) or (table_schema = 'ops' and table_name = any(%s))) order by 1, 2",
                (list(PARQUET_SCHEMAS), list(OPS_TABLES))).fetchall()]
        for s, t in tables:
            d = out / "parquet" / s
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"{t}.parquet"
            # geography / vector columns become WKB / text via the postgres scanner; everything else keeps its type
            con.execute(f'COPY (SELECT * FROM pg.{s}."{t}") TO \'{f}\' (FORMAT parquet, COMPRESSION zstd)')
            n = con.execute(f"select count(*) from read_parquet('{f}')").fetchone()[0]
            manifest["tables"][f"{s}.{t}"] = {"rows": n, "parquet": str(f.relative_to(out))}
            console.print(f"parquet {s}.{t}: {n:,}")

    ml_src = settings().data_dir / "ml"
    if ml_src.exists():
        shutil.copytree(ml_src, out / "training_sets", dirs_exist_ok=True)

    if dump:
        (out / "database").mkdir(exist_ok=True)
        target = out / "database" / "mip.dump"
        console.print("pg_dump (full database, compressed) — this takes a while …")
        with target.open("wb") as fh:
            subprocess.run(["docker", "exec", CONTAINER, "pg_dump", "-U", "mip", "-d", "mip", "-Fc",
                            "--compress=zstd:5"], stdout=fh, check=True)

    (out / "README.md").write_text(README.format(created=manifest["created_at"], commit=commit))
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            manifest["files"][str(p.relative_to(out))] = {"bytes": p.stat().st_size,
                                                          "sha256": _sha256(p) if p.stat().st_size < 8 << 30 else None}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    total = sum(v["bytes"] for v in manifest["files"].values())
    console.print(f"[green]snapshot[/]: {out} ({total / 1e9:.1f} GB, {len(manifest['files'])} files)")
    return out
