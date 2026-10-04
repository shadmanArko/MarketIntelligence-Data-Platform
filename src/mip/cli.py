"""mip discover | fetch | transform | report — each taking --market berlin-food --source wolt."""

import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from mip.config import load_market
from mip.core import logging as mlog
from mip.settings import ROOT

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Market Intelligence Data Platform")
db_app = typer.Typer(no_args_is_help=True, help="Database migrations and maintenance")
geo_app = typer.Typer(no_args_is_help=True, help="Boundary and H3 grid")
ds_app = typer.Typer(no_args_is_help=True, help="Bulk datasets: download once, register, load to raw")
er_app = typer.Typer(no_args_is_help=True, help="Entity resolution")
ml_app = typer.Typer(no_args_is_help=True, help="Versioned ML training-set exports")
enrich_app = typer.Typer(no_args_is_help=True, help="Deterministic text enrichment (languages, mentions)")
app.add_typer(db_app, name="db")
app.add_typer(geo_app, name="geo")
app.add_typer(ds_app, name="datasets")
app.add_typer(er_app, name="resolve")
app.add_typer(ml_app, name="ml")
app.add_typer(enrich_app, name="enrich")
console = Console()

Market = Annotated[str, typer.Option("--market", "-m", help="market id, e.g. berlin-food")]
Source = Annotated[str, typer.Option("--source", "-s", help="connector, e.g. wolt")]


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    mlog.setup("DEBUG" if verbose else "INFO")


# ------------------------------------------------------------------ db
@db_app.command("migrate")
def db_migrate() -> None:
    from mip.db import migrate

    applied = migrate()
    console.print(f"[green]applied {len(applied)} migration(s)[/] {applied}")


@db_app.command("partitions")
def db_partitions(months_ahead: int = 12) -> None:
    """Make sure monthly partitions exist for raw observations ahead of time."""
    from mip.db import connect

    with connect() as c:
        c.execute(
            "SELECT ops.ensure_month_partition('raw.observations', m::date) FROM generate_series("
            "date_trunc('month', now()), date_trunc('month', now()) + make_interval(months => %s),"
            " interval '1 month') m",
            (months_ahead,),
        )
    console.print("[green]partitions ok[/]")


# ------------------------------------------------------------------ geo
@geo_app.command("boundary")
def geo_boundary(market: Market = "berlin-food") -> None:
    from mip.geo.grid import fetch_boundary

    m = load_market(market)
    if not m.geography.osm_relation_id:
        raise typer.BadParameter("market has no osm_relation_id")
    p = fetch_boundary(m.geography.osm_relation_id, m.boundary_path())
    console.print(f"[green]wrote {p}[/]")


@geo_app.command("grid")
def geo_grid(market: Market = "berlin-food", res: int | None = None) -> None:
    """Load the market's H3 cells (res 7/8/9) and admin areas into raw.geo_* tables."""
    from mip.geo.load import load_grid

    load_grid(load_market(market), res)


# ------------------------------------------------------------------ pipeline
@app.command()
def sources() -> None:
    """List registered connectors and whether the market enables them."""
    from mip.core.connector import get_connector_cls, registered

    m = load_market("berlin-food")
    t = Table("source", "version", "enabled (berlin-food)", "rate limit")
    for s in registered():
        cls = get_connector_cls(s)
        en = m.sources.get(s)
        rl = cls.rate_limit
        t.add_row(s, cls.version, "yes" if en and en.enabled else "no", f"{rl.requests}/{rl.per_seconds}s")
    console.print(t)


@app.command()
def healthcheck(market: Market = "berlin-food", source: Source = "wolt") -> None:
    from mip.core.runner import healthcheck as hc

    raise typer.Exit(0 if hc(load_market(market), source) else 1)


@app.command()
def discover(
    market: Market = "berlin-food",
    source: Source = "wolt",
    limit: int | None = typer.Option(None, help="cap discovered units"),
    refresh: bool = typer.Option(False, help="re-queue tasks that are already done"),
) -> None:
    """Find units of work (grid points, postcodes, accounts, pages) and queue them."""
    from mip.core.runner import discover as disc

    disc(load_market(market), source, limit, refresh)


@app.command()
def fetch(
    market: Market = "berlin-food",
    source: Source = "wolt",
    workers: int = typer.Option(4, "--workers", "-w"),
    max_tasks: int | None = typer.Option(None, help="stop after N tasks"),
    entity: list[str] | None = typer.Option(None, "--entity", "-e", help="only these entity types"),
    skip_health: bool = typer.Option(False),
    refresh_children: bool = typer.Option(False, help="re-queue follow-up tasks already done (refresh runs)"),
) -> None:
    """Work through the queue; resumable — rerun to continue where the last run stopped."""
    from mip.core.runner import fetch as f

    f(load_market(market), source, workers, max_tasks, entity, skip_health, refresh_children)


@app.command()
def run(
    market: Market = "berlin-food",
    source: Source = "wolt",
    workers: int = typer.Option(4, "--workers", "-w"),
    limit: int | None = None,
    refresh: bool = False,
) -> None:
    """discover + fetch in one go."""
    from mip.core.runner import discover as disc
    from mip.core.runner import fetch as f

    m = load_market(market)
    disc(m, source, limit, refresh)
    f(m, source, workers, refresh_children=refresh)


@app.command()
def status(market: Market = "berlin-food", source: str | None = typer.Option(None, "--source", "-s")) -> None:
    """Queue state, raw volumes, quarantine and drift per source."""
    from mip.core.queue import summary
    from mip.db import connect

    with connect() as c:
        t = Table("source", "entity", "status", "tasks")
        for r in summary(c, market, source):
            t.add_row(r["source"], r["entity_type"], r["status"], str(r["n"]))
        console.print(t)
        t2 = Table("source", "entity", "observations", "distinct keys", "last fetched")
        for r in c.execute(
            "SELECT source, entity_type, count(*) n, count(DISTINCT natural_key) k, max(fetched_at) last"
            " FROM raw.observations WHERE market_id=%s AND (%s::text IS NULL OR source=%s) GROUP BY 1,2 ORDER BY 1,2",
            (market, source, source),
        ):
            t2.add_row(r["source"], r["entity_type"], str(r["n"]), str(r["k"]), str(r["last"])[:19])
        console.print(t2)
        q = c.execute("SELECT source, reason, count(*) n FROM ops.quarantine GROUP BY 1,2 ORDER BY 1").fetchall()
        d = c.execute("SELECT source, entity_type, count(*) n FROM ops.schema_drift WHERE NOT acknowledged"
                      " GROUP BY 1,2").fetchall()
        if q:
            console.print("[yellow]quarantine:[/]", [dict(r) for r in q])
        if d:
            console.print("[yellow]unacknowledged schema drift:[/]", [dict(r) for r in d])


@app.command()
def transform(
    select: str | None = typer.Option(None, "--select", help="dbt selector"),
    full_refresh: bool = False,
) -> None:
    """Build staging -> core -> marts -> ml with dbt (gates 2 and 3 run as dbt tests)."""
    cmd = ["dbt", "build", "--project-dir", str(ROOT / "dbt"), "--profiles-dir", str(ROOT / "dbt")]
    if select:
        cmd += ["--select", select]
    if full_refresh:
        cmd.append("--full-refresh")
    raise typer.Exit(subprocess.call(cmd))


@app.command()
def report(market: Market = "berlin-food") -> None:
    """Quality report per source: completeness, volume vs last run, freshness, quarantine."""
    from mip.quality import run_report

    run_report(load_market(market))


# ------------------------------------------------------------------ datasets
@ds_app.command("load")
def ds_load(name: str, market: Market = "berlin-food", version: str | None = None) -> None:
    """Download + register + load a bulk dataset (osm, overture, foursquare, tripadvisor, zensus, ...)."""
    from mip.datasets import load_dataset

    load_dataset(name, load_market(market), version)


@ds_app.command("list")
def ds_list() -> None:
    from mip.db import connect

    with connect() as c:
        t = Table("name", "version", "rows", "raw table", "terms", "loaded")
        for r in c.execute("SELECT * FROM ops.datasets ORDER BY name, loaded_at DESC"):
            t.add_row(r["name"], r["version"], str(r["row_count"]), r["raw_table"] or "", r["terms"] or "",
                      str(r["loaded_at"])[:19])
        console.print(t)


# ------------------------------------------------------------------ resolution
@er_app.command("listings")
def er_listings(threshold: float = 0.9) -> None:
    """Match listings across platforms into stable business ids (Splink + deterministic rules)."""
    from mip.resolution.listings import resolve

    resolve(threshold=threshold)


@er_app.command("review")
def er_review(n: int = 20, domain: str = "listing") -> None:
    """Label grey-zone pairs in the terminal (y / n / s=skip / q=quit)."""
    from mip.resolution.review import review

    review(n, domain)


@er_app.command("evaluate")
def er_evaluate() -> None:
    """Precision / recall against the labelled pairs (gate 2 needs precision >= 0.95)."""
    from mip.resolution.review import evaluate

    evaluate()


@er_app.command("social")
def er_social() -> None:
    from mip.resolution.social import resolve_social

    resolve_social()


@enrich_app.command("languages")
def enrich_languages() -> None:
    from mip.enrich.text import detect_languages

    detect_languages()


@enrich_app.command("content")
def enrich_content() -> None:
    """Tag posts / videos / comments with dishes, communities, occasions and format cues (ops.content_tag)."""
    from mip.enrich.content import tag_content

    tag_content()


@enrich_app.command("mentions")
def enrich_mentions() -> None:
    from mip.enrich.text import find_mentions

    find_mentions()


@ml_app.command("export")
def ml_export_cmd(name: str = typer.Argument("business_features"),
                  as_of: str | None = typer.Option(None, help="cut-off timestamp (UTC); default now")) -> None:
    """Build point-in-time features as of a cut-off and write a registered, versioned Parquet set."""
    from mip.ml_export import export

    export(name, as_of)


@ml_app.command("list")
def ml_list() -> None:
    from mip.db import connect

    with connect() as c:
        t = Table("name", "version", "as of", "rows", "features", "git", "path")
        for r in c.execute("SELECT * FROM ml.training_sets ORDER BY name, version"):
            t.add_row(r["name"], str(r["version"]), str(r["as_of"])[:19], f"{r['row_count']:,}",
                      str(len(r["feature_list"])), r["git_commit"] or "", r["path"])
        console.print(t)


docs_app = typer.Typer(no_args_is_help=True, help="Generated documentation")
app.add_typer(docs_app, name="docs")


@docs_app.command("catalog")
def docs_catalog() -> None:
    """Write docs/data/catalog.md + catalog.json: every table, rows, columns, meaning, example row."""
    from mip.catalog import write_catalog

    write_catalog()


export_app = typer.Typer(no_args_is_help=True, help="Portable copies of the data")
app.add_typer(export_app, name="export")


@export_app.command("snapshot")
def export_snapshot(to: str = typer.Option("data/exports", help="target folder, e.g. /Volumes/MyDrive/dk-data"),
                    dump: bool = typer.Option(True, help="include the full pg_dump backup"),
                    parquet: bool = typer.Option(True, help="include Parquet copies of core / marts / ml")) -> None:
    """Copy everything to a folder / external drive: full DB backup, Parquet tables, training sets, docs."""
    from mip.export_snapshot import snapshot

    snapshot(Path(to), dump=dump, parquet=parquet)


@app.command()
def taxonomy(market: Market = "berlin-food") -> None:
    """Export the taxonomy YAMLs to dbt seed CSVs (cuisines, dishes, communities, greetings, occasion types)."""
    from mip.taxonomy import export_audience_seeds, export_seeds

    export_seeds(load_market(market))
    export_audience_seeds()


if __name__ == "__main__":
    app()
