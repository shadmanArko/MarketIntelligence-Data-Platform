"""Occasion calendar for every Berlin community (2015-2030) and Berlin daily sun / prayer-window times.

* raw.ds_occasion_calendar  one row per (day, community, occasion): national + religious holidays of each
  community's countries from python-holidays (English and native names, estimated flag), mapped to occasion types
  by config/taxonomies/occasions.yaml, plus the rule-based occasions defined there.
* raw.ds_sun_times_berlin   per day: dawn (18° and 12°), sunrise, solar noon, sunset (= iftar), dusk, day length.
  Suhoor ends at dawn; mosque timetables in Germany use 12-18°, so both are given.
"""

import re
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import holidays
import yaml
from astral import Observer
from astral.sun import dawn, dusk, noon, sunrise, sunset
from dateutil.easter import easter
from hijridate import Gregorian, Hijri
from persiantools.jdatetime import JalaliDate

from mip.config import Market
from mip.datasets import already_loaded, console, loader, register, table_name
from mip.db import connect
from mip.settings import ROOT

START, END = 2015, 2030
TZ = ZoneInfo("Europe/Berlin")
BERLIN = Observer(latitude=52.52, longitude=13.405, elevation=34)
TAX = ROOT / "config" / "taxonomies"


def _communities() -> dict:
    return yaml.safe_load((TAX / "communities.yaml").read_text())["communities"]


def _occasions() -> dict:
    return yaml.safe_load((TAX / "occasions.yaml").read_text())


def _classify(name: str, day: date, types: dict) -> str:
    for t, spec in types.items():
        pat = spec.get("match")
        if pat and re.search(pat, name, re.I):
            if t == "christmas" and day.month == 1:
                return "orthodox_christmas"
            return t
    return "other"


def _country_rows(comms: dict, types: dict) -> list[tuple]:
    rows = []
    for cid, c in comms.items():
        for cc in c.get("countries", []):
            try:
                cls = holidays.country_holidays(cc, years=START)
                cats = tuple(cls.supported_categories)
                en = holidays.country_holidays(cc, years=range(START, END + 1), categories=cats,
                                               language="en_US" if "en_US" in cls.supported_languages else None)
                native = holidays.country_holidays(cc, years=range(START, END + 1), categories=cats)
            except (NotImplementedError, KeyError, AttributeError) as e:
                console.print(f"[yellow]holidays {cc}: {e}[/]")
                continue
            for d, names in en.items():
                nat = native.get(d) or ""
                for n in names.split("; "):
                    t = _classify(n, d, types)
                    if t == "other" and nat:
                        t = _classify(nat, d, types)
                    rows.append((d, cid, cc, t, n, nat if nat != names else None, "estimated" in n.lower(),
                                 "python-holidays", None))
    return rows


def _hijri_range(year: int, frm: list[int], to: list[int]) -> list[date]:
    out = []
    for hy in range(Gregorian(year, 1, 1).to_hijri().year, Gregorian(year, 12, 31).to_hijri().year + 1):
        try:
            a = Hijri(hy, frm[0], frm[1]).to_gregorian()
            b = Hijri(hy, to[0], min(to[1], Hijri(hy, to[0], 1).month_length())).to_gregorian()
        except (ValueError, OverflowError):
            continue
        d = a
        while d <= b:
            if d.year == year:
                out.append(d)
            d += timedelta(days=1)
    return out


def _rule_days(rule: dict, year: int) -> list[date]:
    k = rule["kind"]
    days = rule.get("days", 1)
    if k == "hijri_range":
        return _hijri_range(year, rule["from"], rule["to"])
    if k == "persian":
        jy = year - 621
        out = []
        for y in (jy - 1, jy):
            try:
                g = JalaliDate(y, *rule["date"]).to_gregorian()
            except ValueError:
                continue
            if g.year == year:
                out.append(g)
        return out
    if k == "nowruz_last_tuesday":
        nowruz = JalaliDate(year - 621, 1, 1).to_gregorian()
        d = nowruz - timedelta(days=1)
        while d.weekday() != 1:
            d -= timedelta(days=1)
        return [d]    # the celebration is the evening of the last Tuesday
    if k == "fixed":
        m, dd = map(int, rule["date"].split("-"))
        return [date(year, m, dd) + timedelta(days=i) for i in range(days)]
    if k == "easter":
        s = easter(year) + timedelta(days=rule["offset"])
        return [s + timedelta(days=i) for i in range(days)]
    if k == "nth_weekday":
        m, wd, n = rule["month"], rule["weekday"], rule["n"]
        if n > 0:
            d = date(year, m, 1)
            d += timedelta(days=(wd - d.weekday()) % 7 + 7 * (n - 1))
        else:
            d = (date(year, m + 1, 1) if m < 12 else date(year + 1, 1, 1)) - timedelta(days=1)
            d -= timedelta(days=(d.weekday() - wd) % 7)
        return [d + timedelta(days=rule.get("offset", 0))]
    if k == "advent":
        xmas = date(year, 12, 25)
        first = xmas - timedelta(days=(xmas.weekday() + 1) % 7 or 7) - timedelta(weeks=3)
        d, out = first + timedelta(days=rule.get("offset", 0)), []
        while d <= date(year, 12, 23):
            out.append(d)
            d += timedelta(days=1)
        return out
    if k == "holiday_of":
        h = holidays.country_holidays(rule["country"], years=year, language="en_US")
        out = []
        for d0, n in h.items():
            if any(re.search(rule["match"], x) for x in n.split("; ")):
                s = d0 + timedelta(days=rule.get("offset", 0))
                out += [s + timedelta(days=i) for i in range(days)]
        return out
    if k == "month_end":
        out = []
        for m in range(1, 13):
            d = (date(year, m + 1, 1) if m < 12 else date(year + 1, 1, 1)) - timedelta(days=1)
            while d.weekday() >= 5:
                d -= timedelta(days=1)
            out.append(d)
        return out
    raise ValueError(f"unknown rule kind {k}")


def _rule_rows(comms: dict, occ: dict) -> list[tuple]:
    rows = []
    for rule in occ["rules"]:
        target = rule["communities"]
        if target == "all":
            cids = ["all"]
        elif target == "muslim":
            cids = [c for c, v in comms.items() if "muslim" in v.get("religion_mix", [])]
        else:
            cids = target
        for y in range(START, END + 1):
            for d in _rule_days(rule, y):
                for cid in cids:
                    off = comms.get(cid, {}).get("moon_offset", 0) if rule["kind"] == "hijri_range" else 0
                    rows.append((d + timedelta(days=off), cid, None, rule["type"], rule["type"].replace("_", " "),
                                 None, rule["kind"] == "hijri_range", "rule:" + rule["kind"], rule["kind"]))
    return rows


@loader("occasions")
def load_occasions(market: Market, version: str | None = None) -> None:
    import hashlib

    digest = hashlib.sha256((TAX / "communities.yaml").read_bytes() + (TAX / "occasions.yaml").read_bytes()
                            ).hexdigest()[:12]
    name, ver = "occasion_calendar", version or f"{START}-{END}-{digest}"
    if already_loaded(name, ver):
        console.print("occasion calendar already loaded")
        return
    comms, occ = _communities(), _occasions()
    rows = sorted(set(_country_rows(comms, occ["types"]) + _rule_rows(comms, occ)),
                  key=lambda r: (r[0], r[1], r[3], r[4]))
    tbl = table_name(name, ver)
    with connect() as c:
        c.execute(f"""DROP TABLE IF EXISTS {tbl};
          CREATE TABLE {tbl} (day date, community_id text, country text, occasion_type text,
            holiday_name text, holiday_name_native text, is_estimated boolean, source text, rule_kind text)""")
        with c.cursor().copy(f"COPY {tbl} FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
    register(name, ver, "python-holidays (all categories) + config/taxonomies/{communities,occasions}.yaml rules",
             tbl, "holidays: MIT; Islamic dates estimated (Umm al-Qura, ±1 day; moon_offset per"
             " community)", refresh_cadence="on taxonomy change", meta={"rows": len(rows)})
    console.print(f"[green]occasion calendar:[/] {len(rows)} rows")
    _load_sun()


def _load_sun() -> None:
    name, ver = "sun_times_berlin", f"{START}-{END}"
    if already_loaded(name, ver):
        return
    tbl = table_name(name, ver)
    rows = []
    d = date(START, 1, 1)

    def t(fn, **kw):
        try:
            return fn(BERLIN, date=d, tzinfo=TZ, **kw)
        except ValueError:      # sun never reaches that depression (Berlin summer nights)
            return None

    while d <= date(END, 12, 31):
        sr, ss = t(sunrise), t(sunset)
        rows.append((d, t(dawn, depression=18), t(dawn, depression=12), sr, t(noon), ss, t(dusk, depression=18),
                     round((ss - sr).total_seconds() / 3600, 3) if sr and ss else None))
        d += timedelta(days=1)
    with connect() as c:
        c.execute(f"""DROP TABLE IF EXISTS {tbl};
          CREATE TABLE {tbl} (day date PRIMARY KEY, dawn_18 timestamptz, dawn_12 timestamptz,
            sunrise timestamptz, solar_noon timestamptz, sunset timestamptz, dusk_18 timestamptz, day_length_h float8)""")
        with c.cursor().copy(f"COPY {tbl} FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
    register(name, ver, "astral (computed, 52.52N 13.405E)", tbl,
             "computed", refresh_cadence="never")
    console.print(f"[green]sun times:[/] {len(rows)} days")
