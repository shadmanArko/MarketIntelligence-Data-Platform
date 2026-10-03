"""Berlin residents by citizenship and migration background (Amt für Statistik Berlin-Brandenburg, Einwohnerregister,
half-yearly). Audience sizes per community, per district (Bezirk) and per LOR planning area.

* SB A I 5   sheet T9  migration background by Bezirk x 24 origin areas x sex
             sheet T10 foreign residents by every citizenship x sex x age group (Berlin total)
* SB A I 16  sheet T4  migration background by LOR planning area x 24 origin areas

The XLSX files are human-formatted (multi-row headers, section rows). They are kept unchanged on disk and unpivoted
losslessly into one long table: one row per numeric cell with its row keys, section and column header path.
Download URLs carry hashes and change every release, so they are scraped from the landing pages.
"""

import re
from datetime import date

import httpx
import openpyxl

from mip.config import Market
from mip.datasets import already_loaded, bulk_dir, console, loader, register, sha256_file, table_name
from mip.db import connect

PAGES = {"a-i-5-hj": {"T9": (2, 4, 1), "T10 G1": (2, 4, 2)},     # sheet -> (first header row, last header row, key cols)
         "a-i-16-hj": {"T4": (2, 4, 4), "Schlüssel": (2, 2, 4)}}
BASE = "https://www.statistik-berlin-brandenburg.de/"
UA = {"User-Agent": "mip-market-intel/0.1 (market research data platform)"}


def _clean(v) -> str | None:
    if v is None:
        return None
    s = re.sub(r"-\n", "", str(v))
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _labels(rows: list[tuple], ncol: int) -> list[str]:
    out = [[] for _ in range(ncol)]
    for hi, row in enumerate(rows):
        last = None
        for c in range(ncol):
            v = _clean(row[c]) if c < len(row) else None
            if v is None and hi < len(rows) - 1:
                v = last                       # merged group headers span to the right
            else:
                last = v if v is not None else last
            if v and (not out[c] or out[c][-1] != v):
                out[c].append(v)
    return [" / ".join(x) for x in out]


def _unpivot(path, sheets: dict) -> list[tuple]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    cells = []
    for sh, (h0, h1, nkeys) in sheets.items():
        rows = list(wb[sh].iter_rows(values_only=True))
        ncol = max(len(r) for r in rows)
        labels = _labels(rows[h0:h1 + 1], ncol)
        section, keys_ffill = [], [None] * nkeys
        for i, row in enumerate(rows[h1 + 1:], start=h1 + 1):
            row = list(row) + [None] * (ncol - len(row))
            nums = [(c, v) for c, v in enumerate(row) if c >= nkeys and isinstance(v, (int, float))]
            texts = [_clean(v) for v in row if isinstance(v, str) and _clean(v)]
            if sh == "Schlüssel":
                if row[3] and row[4]:
                    cells.append((sh, i, None, *[_clean(x) for x in row[:4]], "Planungsraumname", 4, None,
                                  _clean(row[4])))
                continue
            if not nums:
                texts = list(dict.fromkeys(texts))     # wide tables repeat the label on the right half
                if len(texts) == 1 and len(texts[0]) < 60:
                    nxt = rows[i + 1] if i + 1 < len(rows) else ()
                    nxt_is_label = any(isinstance(v, str) for v in nxt) and not any(
                        isinstance(v, (int, float)) for v in nxt)
                    # a label directly followed by another label is a group ("Ausländer" -> "männlich")
                    section = [texts[0]] if nxt_is_label else section[:1] + [texts[0]] if len(section) else [texts[0]]
                continue
            keys = []
            for k in range(nkeys):
                v = _clean(row[k])
                if v is not None:
                    keys_ffill[k] = v
                    keys_ffill[k + 1:] = [None] * (nkeys - k - 1)
                keys.append(keys_ffill[k] if v is None and k < nkeys - 1 else v)
            keys += [None] * (4 - nkeys)
            for c, v in nums:
                cells.append((sh, i, " / ".join(section) or None, *keys[:4], labels[c], c, float(v), None))
    return cells


def _release(fname: str) -> date:
    m = re.search(r"_(\d{4})h0?([12])_", fname)
    y, h = int(m.group(1)), int(m.group(2))
    return date(y, 6, 30) if h == 1 else date(y, 12, 31)


@loader("afs_population")
def load_afs_population(market: Market, version: str | None = None) -> None:
    rows, files = [], []
    for page, sheets in PAGES.items():
        html = httpx.get(BASE + page, headers=UA, timeout=60, follow_redirects=True).text
        urls = sorted(set(u for u in re.findall(r'https://download\.statistik-berlin-brandenburg\.de/[^"]+\.xlsx', html)
                          if re.search(r"_\d{4}h0?\d_BE\.xlsx$", u)))
        for url in urls:
            fname = url.rsplit("/", 1)[1]
            path = bulk_dir("afs_population") / fname
            if not path.exists():
                r = httpx.get(url, headers=UA, timeout=120, follow_redirects=True)
                r.raise_for_status()
                path.write_bytes(r.content)
            rel = _release(fname)
            files.append({"file": fname, "url": url, "sha256": sha256_file(path), "reference_date": rel.isoformat()})
            for cell in _unpivot(path, sheets):
                rows.append((fname.split("_")[1], rel, *cell))
    ver = version or max(f["reference_date"] for f in files)
    name = "afs_population"
    if already_loaded(name, ver):
        console.print("afs population already loaded")
        return
    tbl = table_name(name, ver)
    with connect() as c:
        c.execute(f"""DROP TABLE IF EXISTS {tbl};
          CREATE TABLE {tbl} (report text, reference_date date, sheet text, row_no int, section text,
            key1 text, key2 text, key3 text, key4 text, column_label text, col_no int, value float8, text_value text)""")
        with c.cursor().copy(f"COPY {tbl} FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
    register(name, ver, BASE + "a-i-5-hj , " + BASE + "a-i-16-hj", tbl,
             "Amt für Statistik Berlin-Brandenburg; free reuse with source attribution (dl-de/by-2-0)",
             refresh_cadence="half-yearly", meta={"files": files, "cells": len(rows)})
    console.print(f"[green]afs population:[/] {len(rows):,} cells from {len(files)} files")
