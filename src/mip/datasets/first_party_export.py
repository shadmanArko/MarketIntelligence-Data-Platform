"""Tenant social-media exports delivered as files (XLSX from the AI Harness warehouse): kept unchanged in
data/bulk/first_party/ and loaded cell-for-cell into a versioned raw table (version = file checksum). Each file is
one observation of the tenant's posts and metrics; staging takes the latest observation per post across the
warehouse connector (`first_party`) and these files.

Platform reporting gaps travel with the data: Instagram returns no impressions, Threads no reach, and only
Facebook returns clicks — the export stores those as 0; staging turns them into NULL (missing is not zero)."""

from datetime import datetime

import openpyxl

from mip.config import Market
from mip.datasets import already_loaded, bulk_dir, console, loader, register, sha256_file, table_name
from mip.db import connect

COLS = {"Platform": "platform", "Posted (Berlin time)": "posted_berlin", "Type": "content_type", "Caption": "caption",
        "Link": "permalink", "Platform post ID": "external_id", "Impressions": "impressions", "Reach": "reach",
        "Likes": "likes", "Comments": "comments", "Shares": "shares", "Saves": "saves", "Clicks": "clicks",
        "Metrics captured (Berlin time)": "captured_berlin"}


@loader("first_party_export")
def load_first_party_export(market: Market, version: str | None = None) -> None:
    files = sorted(bulk_dir("first_party").glob("*.xlsx"))
    if not files:
        console.print("[yellow]no files in data/bulk/first_party/[/]")
        return
    for f in files:
        digest = sha256_file(f)
        name, ver = "first_party_social_export", digest[:12]
        if already_loaded(name, ver):
            console.print(f"{f.name} already loaded")
            continue
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        rows = list(wb["Posts"].iter_rows(values_only=True))
        head = [COLS.get(h, h) for h in rows[0]]
        recs = []
        for r in rows[1:]:
            d = dict(zip(head, r, strict=False))
            if not d.get("external_id"):
                continue
            def ts(v):
                return v if isinstance(v, datetime) else (datetime.fromisoformat(str(v)) if v else None)
            recs.append((f.name, d["platform"], str(d["external_id"]), ts(d["posted_berlin"]), d.get("content_type"),
                         d.get("caption"), d.get("permalink"),
                         *[None if d.get(k) in (None, "") else int(float(d[k])) for k in
                           ("impressions", "reach", "likes", "comments", "shares", "saves", "clicks")],
                         ts(d["captured_berlin"])))
        tbl = table_name(name, ver)
        with connect() as c:
            c.execute(f"""DROP TABLE IF EXISTS {tbl};
              CREATE TABLE {tbl} (file text, platform text, external_id text, posted_berlin timestamp,
                content_type text, caption text, permalink text, impressions bigint, reach bigint, likes bigint,
                comments bigint, shares bigint, saves bigint, clicks bigint, captured_berlin timestamp)""")
            with c.cursor().copy(f"COPY {tbl} FROM STDIN") as cp:
                for rec in recs:
                    cp.write_row(rec)
        register(name, ver, f"file data/bulk/first_party/{f.name} (AI Harness warehouse export)", tbl,
                 "first-party (Dhaka Kacchi); internal", checksum=digest, local_path=str(f),
                 refresh_cadence="when a new export is delivered", meta={"rows": len(recs), "file": f.name})
        console.print(f"[green]first-party export[/]: {f.name} -> {tbl} ({len(recs)} posts)")
