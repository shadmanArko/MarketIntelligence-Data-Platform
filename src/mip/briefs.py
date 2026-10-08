"""Daily content briefs: for every day and platform, exactly what to make — format, media spec, pillar, occasion,
target community, languages, greeting, bridge dish, hook, shot list, caption rules, hashtags, audio and vibe,
posting window, call to action — with the evidence behind each choice.

Deterministic (no LLM): rules in config/content/playbook.yaml + the occasion calendar, community audiences and
content-performance marts. A content app / LLM agent turns each brief into the actual caption, script and media
(see docs/content-agent-guide.md and docs/content-brief.schema.json).

    uv run mip brief content --days 10 [--start 2026-10-06]   ->  data/briefs/<start>_<days>d.json + .md
"""

import hashlib
import json
import math
from datetime import date, timedelta

import yaml
from rich.console import Console

from mip.db import connect
from mip.settings import ROOT, settings

console = Console()
PLAYBOOK = ROOT / "config" / "content" / "playbook.yaml"
TEXT_FORMATS = {"text_photo", "text_video", "community_post", "multi_image"}
SKIP_TYPES = {"payday", "other", "semester_start", "national_other"}
ROLE_WEIGHT = {"feast": 3.0, "fasting_evening": 3.0, "gift_season": 1.6, "family_meal": 1.4, "party": 1.0,
               "remembrance": 0.0}
LANG_NAME = {"de": "German", "en": "English", "bn": "Bengali", "hi": "Hindi", "ur": "Urdu", "ar": "Arabic",
             "tr": "Turkish", "fa": "Persian", "fa-AF": "Dari", "ps": "Pashto", "ru": "Russian", "uk": "Ukrainian",
             "vi": "Vietnamese", "zh-Hans": "Chinese", "ko": "Korean", "pl": "Polish", "es": "Spanish",
             "it": "Italian", "fr": "French", "pt": "Portuguese", "ne": "Nepali", "kmr": "Kurmanji", "el": "Greek",
             "sr": "Serbian", "uz": "Uzbek", "az": "Azerbaijani", "th": "Thai", "ja": "Japanese", "id": "Indonesian",
             "so": "Somali", "he": "Hebrew", "hy": "Armenian", "si": "Sinhala"}


def _pick(seq, key: str):
    """Stable pseudo-random choice (same inputs -> same plan)."""
    if not seq:
        return None
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return seq[h % len(seq)]


def _weighted(pillars: dict, key: str, exclude: set) -> str:
    items = [(k, v.get("weight", 1)) for k, v in pillars.items() if k not in exclude and v.get("weight", 1) > 0]
    total = sum(w for _, w in items)
    x = (int(hashlib.md5(key.encode()).hexdigest(), 16) % 10_000) / 10_000 * total
    for k, w in items:
        x -= w
        if x <= 0:
            return k
    return items[-1][0]


def _load(start: date, end: date) -> dict:
    with connect() as c:
        occ = c.execute("""
            select day, community_id, community, occasion_type, holiday_names, holiday_names_native, food_role, tone,
                   content_window_start, greeting, greeting_translit, greeting_needs_review, bridge_dishes,
                   coalesce(berlin_citizens, case when community_id = 'all' then 3900000 end) as berlin_citizens,
                   top_districts_mh, iftar_local, suhoor_ends_local, berlin_events, countries
            from marts.occasion_content_calendar
            where content_window_start <= %s and day >= %s""", (end, start)).fetchall()
        com = {r["community_id"]: r for r in c.execute("select * from core.community").fetchall()}
        ccount: dict = {}
        for r in c.execute("select community_id, count(*) n from core.community_country group by 1"):
            ccount[r["community_id"]] = r["n"]
        dishes = {}
        for r in c.execute("select community_id, dish_id, native_name, translit, english from core.community_dish"):
            dishes.setdefault(r["community_id"], []).append(r)
        size = {r["community_id"]: r["n"] for r in c.execute(
            "select community_id, max(residents) n from core.community_audience where level = 'berlin_citizens'"
            " and reference_date = (select max(reference_date) from core.community_audience) group by 1")}
        lift = {(r["platform"], r["tag_type"], r["tag_id"]): float(r["mean_lift_vs_platform"]) for r in c.execute(
            "select platform, tag_type, tag_id, mean_lift_vs_platform from marts.content_feature_performance"
            " where posts >= 100")}
        events = c.execute("""
            select distinct on (event_id) name, district, starts_on, ends_on from staging.stg_berlin_events__event
            where ends_on >= %s and starts_on <= %s order by event_id, fetched_at desc""", (start, end)).fetchall()
        cit = {r["citizenship"]: r["residents"] for r in c.execute(
            "select citizenship, residents from staging.stg_afs__citizenship"
            " where not is_aggregate and reference_date = (select max(reference_date) from staging.stg_afs__citizenship)")}
    country_people: dict = {}
    for cid, cy in yaml.safe_load((ROOT / "config" / "taxonomies" / "communities.yaml").read_text())["communities"].items():
        cs, labels = cy.get("countries") or [], cy.get("afs_citizenship") or []
        if cs and len(labels) >= len(cs):
            country_people[cid] = {cc: cit.get(lab) for cc, lab in zip(cs, labels, strict=False)}
    return {"occasions": occ, "communities": com, "country_count": ccount, "country_people": country_people, "dishes": dishes, "size": size, "lift": lift, "events": events}


def _languages(com: dict | None) -> list[str]:
    langs = ["de", "en"]
    if com:
        for lg in (com.get("languages") or "").split("|"):
            if lg and lg not in langs:
                langs.insert(1, lg)
                break
    return langs


def _theme(day: date, data: dict, pb: dict) -> dict | None:
    """The occasion with the strongest claim on this day: food role x audience size x closeness to the day."""
    best, best_score = None, 0.0
    for o in data["occasions"]:
        if o["occasion_type"] in SKIP_TYPES or not (o["content_window_start"] <= day <= o["day"]):
            continue
        w = ROLE_WEIGHT.get(o["food_role"], 1.0)
        people = o["berlin_citizens"] or 1000
        n_c = data["country_count"].get(o["community_id"], 0)
        if n_c > 1 and o["countries"]:      # e.g. Canadian Thanksgiving is not an American / British occasion
            per = data["country_people"].get(o["community_id"], {})
            known = [per.get(cc) for cc in o["countries"] if per.get(cc) is not None]
            people = sum(known) if known else people * len(o["countries"]) / n_c
        share = ((pb.get("occasion_audience") or {}).get(o["occasion_type"]) or {}).get("share", {})
        people *= share.get(o["community_id"], 1.0)
        home = pb.get("home_community") or {}
        if o["community_id"] == home.get("id"):
            people *= float(home.get("weight", 1.0))
        if o["occasion_type"] == "national_day" and people < 20000:
            continue
        if people < 5000:
            continue                        # too few Berliners celebrate it to steer a whole day
        days_to = (o["day"] - day).days
        span = max(1, (o["day"] - o["content_window_start"]).days)
        closeness = 1.0 + 1.5 * (1 - days_to / span)
        score = w * math.sqrt(people) / 100 * closeness
        if o["food_role"] == "remembrance" and o["day"] == day:
            score = 0.01            # handled as a note, never a sales theme
        if score > best_score:
            best, best_score = o, score
    return {**best, "score": round(best_score, 2)} if best else None


def _scrub(text, blocked: list[str]):
    """Drop holiday names that contain a blocked (religious) word."""
    if text is None:
        return None
    if isinstance(text, list):
        kept = [t for t in text if not any(b.lower() in str(t).lower() for b in blocked)]
        return kept or None
    return None if any(b.lower() in str(text).lower() for b in blocked) else text


def _present(theme: dict | None, pb: dict) -> dict | None:
    """Apply occasion_presentation: neutral label, target community, greeting, hashtags; scrub religious words."""
    if not theme:
        return None
    blocked = pb.get("blocked_words", [])
    pres = (pb.get("occasion_presentation") or {}).get(theme["occasion_type"])
    t = dict(theme)
    t["label"] = theme["occasion_type"].replace("_", " ")
    t["public_id"] = theme["occasion_type"]
    t["holiday_names"] = _scrub(theme["holiday_names"], blocked)
    t["holiday_names_native"] = _scrub(theme["holiday_names_native"], blocked)
    if _scrub(t.get("greeting"), blocked) is None:
        t["greeting"] = t["greeting_translit"] = None
    if pres:
        t["label"] = pres["label"]
        t["public_id"] = pres.get("id", theme["occasion_type"])
        t["holiday_names"] = [pres["label"]]
        t["holiday_names_native"] = None
        if pres.get("community"):
            t["community_id"] = pres["community"]
            t["community"] = None
        g = pres.get("greeting")
        if g:
            t["greeting"], t["greeting_translit"] = g["text"], g["translit"]
            t["greeting_needs_review"] = bool(g.get("review"))
        t["hashtags_override"] = pres.get("hashtags")
    return t


def _solemn(day: date, data: dict) -> list[dict]:
    return [o for o in data["occasions"] if o["day"] == day and o["tone"] == "solemn"
            and (o["berlin_citizens"] or 0) >= 3000]


def build_plan(start: date, days: int) -> dict:
    pb = yaml.safe_load(PLAYBOOK.read_text())
    end = start + timedelta(days=days - 1)
    data = _load(start, end)
    top_coms = sorted((c for c in data["size"] if c not in ("german", "anglo", "french")),
                      key=lambda c: -data["size"][c])[:14]
    plan = {"brand": pb["brand"], "start": start.isoformat(), "days": days, "generated_by": "mip brief content",
            "playbook": str(PLAYBOOK.relative_to(ROOT)), "items": [], "day_themes": []}
    used_pillar: dict[str, list[str]] = {}
    for i in range(days):
        d = start + timedelta(days=i)
        wd = d.isoweekday()
        theme = _present(_theme(d, data, pb), pb)
        bridge_com = theme["community_id"] if theme and theme["community_id"] not in (None, "all") else \
            top_coms[i % len(top_coms)]
        com = data["communities"].get(bridge_com)
        if theme and theme.get("community") is None:
            theme["community"] = (com or {}).get("label")
        dish = _pick(data["dishes"].get(bridge_com, []), f"{d}{bridge_com}")
        solemn = _solemn(d, data)
        events = [e for e in data["events"] if e["starts_on"] <= d <= e["ends_on"]]
        plan["day_themes"].append({
            "date": d.isoformat(), "weekday": d.strftime("%A"),
            "theme": theme["label"] if theme else "evergreen",
            "occasion_day": theme["day"].isoformat() if theme else None,
            "community": theme["community"] if theme else (com or {}).get("label"),
            "solemn_today": [f"{s['occasion_type']} ({s['community']})" for s in solemn],
            "berlin_events": [e["name"] for e in events][:5]})
        for platform, spec in pb["platforms"].items():
            for n, slot in enumerate(spec["daily"]):
                if wd not in slot["weekdays"]:
                    continue
                if slot.get("every_n_weeks") and (d.isocalendar().week % slot["every_n_weeks"]):
                    continue
                fmt = slot["format"]
                key = f"{d}|{platform}|{n}"
                # how much of the day follows the occasion: the first slot per platform during the lead-up,
                # every slot in the last 2 days and on the day itself; the rest stays evergreen
                on_theme = bool(theme) and ((theme["day"] - d).days <= 2 or n == 0) \
                    and platform not in pb.get("no_occasion_platforms", [])
                if on_theme and theme["food_role"] in pb["occasions"]:
                    occ_rule = pb["occasions"][theme["food_role"]]
                    pillar = _pick(occ_rule["pillars"], key) or _weighted(pb["pillars"], key, set())
                else:
                    occ_rule = None
                    recent = set(used_pillar.get(platform, [])[-2:])
                    pillar = _weighted(pb["pillars"], key, recent | {"halal_trust"})
                used_pillar.setdefault(platform, []).append(pillar)
                if pillar == "community_bridge" and bridge_com == (pb.get("home_community") or {}).get("id"):
                    pillar = "dum_reveal"       # our own dish: show it, don't compare it
                p = pb["pillars"][pillar]
                f = pb["formats"][fmt]
                text_first = fmt in TEXT_FORMATS
                window = pb["windows"][occ_rule.get("window", slot["window"])] if occ_rule and occ_rule.get("window") \
                    else pb["windows"][slot["window"]]
                if on_theme and theme["occasion_type"] in ("ramadan_period", "iftar_season_peak") and theme["iftar_local"]:
                    window = f"60-90 min before iftar ({theme['iftar_local']} Berlin)"
                langs = _languages(com) if (on_theme or pillar == "community_bridge") else ["de", "en"]
                occ_lang = on_theme and ((pb.get("occasion_audience") or {}).get(theme["occasion_type"]) or {}).get("language")
                if occ_lang:
                    langs = ["de", occ_lang, "en"]
                if platform == "reddit":
                    langs = ["en", "de"]
                tags = list(pb["hashtags"]["core"][:2])
                tags += p.get("hashtags", [])
                if on_theme:
                    tags += theme.get("hashtags_override") or pb["hashtags"]["occasion"].get(theme["occasion_type"], [])
                tags += [_pick(pb["hashtags"]["boost"], key)]
                cap = f.get("hashtags", [0, 5])[1]
                tags = list(dict.fromkeys(t for t in tags if t))[:cap] if cap else []
                evidence = [f"pillar {pillar}: {p.get('lift', 'n/a')}"]
                for cue in p.get("cues", []):
                    v = data["lift"].get((platform if platform in ("tiktok", "youtube", "reddit") else "tiktok", "cue", cue))
                    if v is not None:
                        evidence.append(f"{cue} lift {v:+.2f} ({platform if platform in ('tiktok', 'youtube', 'reddit') else 'tiktok'})")
                if on_theme:
                    v = data["lift"].get(("tiktok", "occasion", theme["occasion_type"].replace("_period", "")))
                    if v is not None:
                        evidence.append(f"occasion {theme['public_id']} lift {v:+.2f} (tiktok)")
                item = {
                    "date": d.isoformat(), "weekday": d.strftime("%a"), "platform": platform, "format": fmt,
                    "post_window_berlin": window, "pillar": pillar,
                    "objective": "reach new people" if fmt in ("reel", "short_video", "short") else
                                 "saves and shares" if fmt in ("carousel", "photo_album", "multi_image") else
                                 "conversation" if fmt in ("text_photo", "text_video", "community_post") else "watch time",
                    "occasion": None if not on_theme else {
                        "type": theme["public_id"], "label": theme["label"], "date": theme["day"].isoformat(),
                        "names": theme["holiday_names"], "names_native": theme["holiday_names_native"],
                        "community": theme["community"], "tone": theme["tone"],
                        "days_until": (theme["day"] - d).days},
                    "target_community": {"id": bridge_com, "label": (com or {}).get("label"),
                                         "berlin_residents": data["size"].get(bridge_com),
                                         "top_districts": theme["top_districts_mh"] if theme else None},
                    "languages": [{"code": lg, "name": LANG_NAME.get(lg, lg)} for lg in langs],
                    "greeting": None if not (on_theme and theme["greeting"] and (occ_rule or {}).get("greeting")) else {
                        "text": theme["greeting"], "translit": theme["greeting_translit"],
                        "needs_native_review": bool(theme["greeting_needs_review"])},
                    "bridge_dish": None if not dish or pillar != "community_bridge" else {"native": dish["native_name"], "translit": dish["translit"],
                                                          "english": dish["english"]},
                    "media": {k: v for k, v in f.items() if k not in ("note",)},
                    "idea": p["idea"], "hook": p.get("text_hook", p["hook"]) if text_first else p["hook"],
                    "shot_list": [] if text_first else p.get("shots", []),
                    "caption_rules": {
                        "first_line": "the hook as text, max 60 characters, no greeting before the hook",
                        "languages": f"German first; then {LANG_NAME.get(langs[1], langs[1])} line" if len(langs) > 2
                                     else "German, then one English line",
                        "must_include": pb["brand"]["always_say"],
                        "cta": (occ_rule or {}).get("cta", "order on Lieferando / Wolt — link in bio"),
                        "length": f.get("text_chars", [80, 300])},
                    "hashtags": tags,
                    "audio": pb["audio"].get(platform, {}),
                    "notes": [x for x in (slot.get("note"), f.get("note"), (occ_rule or {}).get("note")) if x],
                    "evidence": evidence,
                    "do_not": pb["brand"]["never"],
                }
                if solemn:
                    item["notes"].append("solemn day for " + ", ".join(f"{s['community']} ({s['occasion_type']})"
                                                                       for s in solemn) + ": no celebratory sales tone")
                if events:
                    item["notes"].append("Berlin events today: " + "; ".join(f"{e['name']} ({e['district']})"
                                                                            for e in events[:3]))
                plan["items"].append(item)
    return plan


def _md(plan: dict) -> str:
    L = [f"# Content plan {plan['start']} — {plan['days']} days", "",
         "Generated by `mip brief content` from the occasion calendar, Berlin audiences and content-performance data. "
         "Each row is one piece of content; the JSON file has the full brief for the content app.", ""]
    for t in plan["day_themes"]:
        L.append(f"## {t['weekday']} {t['date']} — theme: {t['theme']}"
                 + (f" (for {t['community']}, on {t['occasion_day']})" if t["occasion_day"] else
                    f" (bridge community: {t['community']})"))
        if t["solemn_today"]:
            L.append(f"_Solemn today: {', '.join(t['solemn_today'])}_")
        L += ["", "| Platform | Format | When (Berlin) | Pillar | Hook | Languages | Hashtags |", "|---|---|---|---|---|---|---|"]
        for it in (x for x in plan["items"] if x["date"] == t["date"]):
            L.append(f"| {it['platform']} | {it['format']} | {it['post_window_berlin']} | {it['pillar']} | {it['hook']} | "
                     f"{', '.join(lg['name'] for lg in it['languages'])} | {' '.join('#' + h for h in it['hashtags'])} |")
        L.append("")
    return "\n".join(L)


def write_plan(start: date, days: int) -> tuple:
    plan = build_plan(start, days)
    out = settings().data_dir / "briefs"
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{start.isoformat()}_{days}d"
    (out / f"{stem}.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False, default=str))
    (out / f"{stem}.md").write_text(_md(plan))
    (out / f"{stem}.html").write_text(_html(plan))
    console.print(f"[green]content plan[/]: {len(plan['items'])} briefs over {days} days -> {out / stem}.json / .md")
    return out / f"{stem}.json", out / f"{stem}.md"


PLATFORM_LABEL = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube", "facebook": "Facebook",
                  "threads": "Threads", "x": "X", "linkedin": "LinkedIn", "reddit": "Reddit"}
FORMAT_LABEL = {"reel": "Reel", "short_video": "Video", "short": "Short", "long_video": "Long video", "carousel": "Carousel",
                "stories": "Stories", "photo_album": "Photo album", "text_photo": "Text + photo", "text_video": "Post",
                "multi_image": "Multi-image post", "community_post": "Community post"}


def _html(plan: dict) -> str:
    from html import escape as e

    css = """
:root{--bg:#f5f6f3;--surface:#fff;--fg:#1d2420;--muted:#5b6660;--line:#dfe3dd;--accent:#0e5a45;--saffron:#b9770e;--chip:#e8efe9;
--display:"Bricolage Grotesque","Avenir Next","Segoe UI",sans-serif;--body:"IBM Plex Sans","Noto Sans","Noto Sans Bengali","Noto Naskh Arabic",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#131714;--surface:#1a201c;--fg:#e6ebe7;--muted:#9aa69f;--line:#2c342f;--accent:#5cc39d;--saffron:#e3a945;--chip:#223029;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#131714;--surface:#1a201c;--fg:#e6ebe7;--muted:#9aa69f;--line:#2c342f;--accent:#5cc39d;--saffron:#e3a945;--chip:#223029;color-scheme:dark}
*{box-sizing:border-box}body{background:var(--bg);color:var(--fg);font:14px/1.55 var(--body);margin:0}
.wrap{max-width:1180px;margin:0 auto;padding-inline:18px;padding-block:36px 64px}
h1,h2{font-family:var(--display);margin:0;text-wrap:balance}h1{font-size:clamp(1.9rem,4.5vw,2.8rem);letter-spacing:-.02em}
h2{font-size:1.25rem}.eyebrow{font:500 12px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--saffron)}
.lede{max-width:72ch;font-size:1.05rem;margin:12px 0 0}.meta{color:var(--muted);font-size:13px;max-width:80ch}
.day{margin-top:34px;padding-top:14px;border-top:2px solid var(--fg)}.dayhead{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:baseline}
.theme{font:500 12px/1 var(--mono);padding:5px 8px;border-radius:3px;background:var(--chip);color:var(--accent)}
.solemn{color:var(--saffron);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px;margin-top:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:12px 14px;min-width:0;display:grid;gap:6px}
.top{display:flex;justify-content:space-between;gap:8px;align-items:baseline}.pf{font-weight:600}.fmt{font:12px var(--mono);color:var(--muted)}
.hook{font-size:15px;font-weight:500}.kv{font-size:12.5px;color:var(--muted)}.kv b{color:var(--fg);font-weight:500}
.greet{font-size:15px}.tags{font:12px var(--mono);color:var(--accent);word-break:break-word}
.pill{font:500 11px/1 var(--mono);padding:3px 6px;border-radius:3px;background:var(--chip);color:var(--accent)}
"""
    days = []
    for t in plan["day_themes"]:
        items = [x for x in plan["items"] if x["date"] == t["date"]]
        cards = []
        for it in items:
            g = it.get("greeting")
            occ = it.get("occasion")
            cards.append(f"""<article class="card"><div class="top"><span class="pf">{PLATFORM_LABEL[it['platform']]}</span>
<span class="fmt">{FORMAT_LABEL.get(it['format'], it['format'])} · {e(it['post_window_berlin'])}</span></div>
<div class="hook">{e(it['hook'])}</div>
<div class="kv"><b>{e(it['pillar'].replace('_', ' '))}</b>{' · for ' + e(occ['label']) + (' in ' + str(occ['days_until']) + ' days' if occ['days_until'] else ' (today)') if occ else ''}</div>
<div class="kv">Languages: <b>{e(', '.join(lg['name'] for lg in it['languages']))}</b></div>
{f'<div class="greet">{e(g["text"])} <span class="kv">({e(g["translit"])})</span></div>' if g else ''}
{f'<div class="kv">Bridge dish: <b>{e(it["bridge_dish"]["native"])}</b> ({e(it["bridge_dish"]["english"])})</div>' if it.get('bridge_dish') else ''}
<div class="kv">Media: <b>{e(str(it['media'].get('ratio', '')))}</b>{', ' + '–'.join(map(str, it['media']['length_s'])) + ' s' if it['media'].get('length_s') else ''}{', ' + '–'.join(map(str, it['media']['slides'])) + ' slides' if it['media'].get('slides') else ''}</div>
<div class="kv">Audio: {e(str(it['audio'].get('default', '')))[:140]}</div>
<div class="tags">{' '.join('#' + e(h) for h in it['hashtags'])}</div></article>""")
        head = (f"<h2>{e(t['weekday'])} {e(t['date'])}</h2><span class=\"theme\">"
                + (e(t['theme'].replace('_', ' ')) + ' · ' + e(t['community'] or '') + ' · ' + e(t['occasion_day'] or '')
                   if t['occasion_day'] else 'evergreen · bridge: ' + e(t['community'] or '')) + "</span>")
        sol = f"<span class=\"solemn\">Solemn today: {e(', '.join(t['solemn_today']))}</span>" if t["solemn_today"] else ""
        days.append(f'<section class="day"><div class="dayhead">{head}{sol}</div><div class="grid">{"".join(cards)}</div></section>')
    n = len(plan["items"])
    return f"""<title>Dhaka Kacchi Content Plan</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{css}</style>
<div class="wrap"><div class="eyebrow">Dhaka Kacchi · content plan · {e(plan['start'])} · {plan['days']} days</div>
<h1>Dhaka Kacchi Content Plan</h1>
<p class="lede">{n} posts across Instagram, TikTok, YouTube, Facebook, Threads, X, LinkedIn and Reddit. Each card is one brief: what to film, which hook, in which language, for whom, when to post and with what sound.</p>
<p class="meta">Generated by <code>mip brief content</code> from the occasion calendar, Berlin community sizes and the performance of 1.9 M posts. Rules: <code>config/content/playbook.yaml</code>. Full briefs for the content app: <code>data/briefs/{e(plan['start'])}_{plan['days']}d.json</code>. Greetings marked for review need a native speaker before posting.</p>
{''.join(days)}</div>"""
