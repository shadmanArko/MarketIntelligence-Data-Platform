"""Calendar and weather features: public + school holidays, Islamic and Bengali dates, DWD daily weather."""

import io
import zipfile
from datetime import date, timedelta

import holidays
import httpx
from convertdate import islamic

from mip.config import Market
from mip.datasets import already_loaded, bulk_dir, console, loader, register
from mip.db import connect

DWD = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/"
DWD_STATION = "00433"  # Berlin-Tempelhof
START, END = date(2015, 1, 1), date(2030, 12, 31)


def _islamic_days(year: int) -> dict[date, list[str]]:
    out: dict[date, list[str]] = {}
    for hy in range(islamic.from_gregorian(year, 1, 1)[0], islamic.from_gregorian(year, 12, 31)[0] + 1):
        try:
            r_start = date(*islamic.to_gregorian(hy, 9, 1))
            r_end = date(*islamic.to_gregorian(hy, 10, 1)) - timedelta(days=1)
            fitr = date(*islamic.to_gregorian(hy, 10, 1))
            adha = date(*islamic.to_gregorian(hy, 12, 10))
        except ValueError:
            continue
        d = r_start
        while d <= r_end:
            out.setdefault(d, []).append("ramadan")
            d += timedelta(days=1)
        for i in range(3):
            out.setdefault(fitr + timedelta(days=i), []).append("eid_al_fitr")
            out.setdefault(adha + timedelta(days=i), []).append("eid_al_adha")
    return out


@loader("holidays")
def load_calendar(market: Market, version: str | None = None) -> None:
    name, ver = "calendar_berlin", f"{START.year}-{END.year}"
    if already_loaded(name, ver):
        console.print("calendar already loaded")
        return
    de = holidays.country_holidays("DE", subdiv="BE", years=range(START.year, END.year + 1), language="de")
    school: dict[date, str] = {}
    for y in range(START.year, END.year + 1):
        try:
            r = httpx.get(f"https://ferien-api.de/api/v1/holidays/BE/{y}", timeout=30)
            for f in r.json() if r.status_code == 200 else []:
                d, e = date.fromisoformat(f["start"][:10]), date.fromisoformat(f["end"][:10])
                while d <= e:
                    school[d] = f["name"]
                    d += timedelta(days=1)
        except Exception as ex:
            console.print(f"[yellow]school holidays {y}: {ex}[/]")
    isl: dict[date, list[str]] = {}
    for y in range(START.year, END.year + 1):
        for d, tags in _islamic_days(y).items():
            isl.setdefault(d, []).extend(tags)
    rows = []
    d = START
    while d <= END:
        tags = sorted(set(isl.get(d, [])))
        rows.append((d, d.isoweekday(), d.isoweekday() >= 6, de.get(d), d in de, school.get(d), d in school,
                     "ramadan" in tags, "eid_al_fitr" in tags, "eid_al_adha" in tags,
                     (d.month, d.day) == (4, 14),     # Pohela Boishakh (Bengali new year)
                     (d.month, d.day) == (2, 21),     # International Mother Language Day (Ekushey)
                     (d.month, d.day) == (12, 16),    # Bangladesh Victory Day
                     (d.month, d.day) == (3, 26)))    # Bangladesh Independence Day
        d += timedelta(days=1)
    with connect() as c:
        c.execute("""DROP TABLE IF EXISTS raw.ds_calendar_berlin;
          CREATE TABLE raw.ds_calendar_berlin (day date PRIMARY KEY, iso_weekday smallint, is_weekend boolean,
            public_holiday text, is_public_holiday boolean, school_holiday text, is_school_holiday boolean,
            is_ramadan boolean, is_eid_al_fitr boolean, is_eid_al_adha boolean, is_pohela_boishakh boolean,
            is_ekushey boolean, is_bd_victory_day boolean, is_bd_independence_day boolean)""")
        with c.cursor().copy("COPY raw.ds_calendar_berlin FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
    register(name, ver, "python-holidays + ferien-api.de + convertdate (tabular Islamic calendar)",
             "raw.ds_calendar_berlin", "holidays: MIT; ferien-api.de: free API; Islamic dates computed (±1 day)",
             refresh_cadence="yearly")


@loader("weather")
def load_weather(market: Market, version: str | None = None) -> None:
    name = "dwd_daily_berlin_tempelhof"
    ver = version or date.today().isoformat()
    if already_loaded(name, ver):
        console.print("weather already loaded")
        return
    listing = httpx.get(DWD + "historical/", timeout=60).text
    import re

    hist = sorted(set(re.findall(rf"tageswerte_KL_{DWD_STATION}_\d+_\d+_hist\.zip", listing)))[-1]
    frames = []
    for url in (DWD + "historical/" + hist, DWD + f"recent/tageswerte_KL_{DWD_STATION}_akt.zip"):
        r = httpx.get(url, timeout=300)
        r.raise_for_status()
        (bulk_dir("dwd") / url.rsplit("/", 1)[1]).write_bytes(r.content)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            member = next(n for n in z.namelist() if n.startswith("produkt_klima_tag"))
            frames.append(z.read(member).decode("latin-1"))
    rows = {}
    for text in frames:  # recent overrides historical on overlap
        lines = text.splitlines()
        header = [h.strip().lower() for h in lines[0].split(";")]
        for ln in lines[1:]:
            vals = [v.strip() for v in ln.split(";")]
            if len(vals) < len(header):
                continue
            rec = dict(zip(header, vals, strict=False))
            d = date(int(rec["mess_datum"][:4]), int(rec["mess_datum"][4:6]), int(rec["mess_datum"][6:8]))
            if d < START:
                continue

            def f(k, rec=rec):
                v = rec.get(k)
                return None if v in (None, "", "-999") else float(v)

            rows[d] = (d, f("tmk"), f("txk"), f("tnk"), f("rsk"), f("sdk"), f("fm"), f("upm"), f("shk_tag"), f("nm"))
    with connect() as c:
        c.execute("""DROP TABLE IF EXISTS raw.ds_dwd_daily_berlin;
          CREATE TABLE raw.ds_dwd_daily_berlin (day date PRIMARY KEY, temp_mean_c float8, temp_max_c float8,
            temp_min_c float8, precipitation_mm float8, sunshine_h float8, wind_mean_ms float8,
            humidity_pct float8, snow_depth_cm float8, cloud_cover_oktas float8)""")
        with c.cursor().copy("COPY raw.ds_dwd_daily_berlin FROM STDIN") as cp:
            for r in sorted(rows.values()):
                cp.write_row(r)
    register(name, ver, DWD + "  (station 00433 Berlin-Tempelhof)", "raw.ds_dwd_daily_berlin",
             "DWD open data, CC BY 4.0", refresh_cadence="daily")
