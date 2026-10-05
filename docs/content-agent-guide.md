# Content agent guide: turning daily briefs into posts

How a content app or a set of LLM agents should use the data platform to produce Dhaka Kacchi's social-media content
every day, on every platform, in the right language for the right community.

## 1. The pipeline

```
data platform (weekly refresh)                      content app (your agents)                       back to the platform
──────────────────────────────                      ─────────────────────────                       ────────────────────
occasion calendar ─┐
Berlin audiences ──┤   mip brief content            1 Planner    reads the plan, groups shoots
performance marts ─┼─► --days 10/15/30  ──► JSON ─► 2 Writer     captions, scripts, on-screen text      published post ids
playbook.yaml ─────┘   (one brief per post)         3 Producer   shot list, edit plan, image layout ─►  + metrics (first_party,
research priors ───┘                                4 Checker    rules + legal + language QA            instagram_graph, tiktok,
                                                    5 Human      approves, films, posts                 youtube) ─► next week's
                                                                                                         plan learns from it
```

1. **Generate the plan:** `uv run mip brief content --days 15` writes `data/briefs/<start>_15d.json` (machine) and
   `.md` (human). It is deterministic: the same data gives the same plan. Regenerate after each Sunday refresh.
2. **The app reads the JSON.** The format is in `docs/content-brief.schema.json`. Each `items[]` entry is one piece
   of content: date, platform, format, posting window, pillar, occasion, target community, languages, greeting,
   bridge dish, media spec, idea, hook, shot list, caption rules, hashtags, audio, notes, evidence and `do_not`.
3. **Agents fill in the creative part** (section 3). The brief fixes the strategy; the agent writes the words and
   plans the visuals.
4. **A person approves, films and posts.** Real footage of real food is required: the platforms rank original
   content and penalise reposts, and AI images of the food would mislead customers.
5. **Close the loop.** Store each published post's platform id with its brief id. The weekly refresh collects the
   metrics, and `marts.content_feature_performance` then shows which pillars, hooks, languages and occasions worked
   for your own account. Adjust the weights in `config/content/playbook.yaml`.

## 2. What the brief already decides (do not change it in the app)

| Field | Comes from |
|---|---|
| Which day features which occasion and community | `core.occasion_day`, community size in Berlin (`core.community_audience`), food role, days to go |
| Platform, format, how many posts per day | `platforms:` in playbook.yaml (research cadence) |
| Pillar: what the post is about | occasion rules, or a weighted rotation using lift from our data |
| Language order | German first. The community's language is added for occasion and bridge posts (e.g. Bengali for Durga Puja). |
| Greeting (native script) | `core.community_greeting`. `needs_native_review: true` means a native speaker must approve it. |
| Bridge dish | the target community's own meat-and-rice dish (`core.community_dish`) |
| Media spec | ratio, resolution, length, slides, safe zones, on-screen captions |
| Hashtags | data-backed bank, already within each platform's limit |
| Audio and vibe | per-platform licensing rule + energy + vibe words; TikTok tracks in `marts.audio_performance` |
| Posting window | Berlin time, before the 18:00 order peak; in Ramadan, 60–90 minutes before iftar |
| Evidence | the lift numbers behind the choice, so a person can see why |

## 3. What the agent must produce for each brief

Return this JSON for every brief, with the same `date`, `platform` and `format` keys:

```json
{
  "brief_ref": {"date": "2026-10-17", "platform": "instagram", "format": "reel"},
  "caption": {"de": "...", "bn": "...", "en": "..."},
  "first_line": "max 60 characters, the hook",
  "on_screen_text": [{"t": "0.0-1.5s", "text": "..."}, {"t": "1.5-4s", "text": "..."}],
  "script": [{"t": "0-2s", "shot": "macro: knife breaks the dough seal", "audio": "seal crack (original)", "voiceover": null},
             {"t": "2-5s", "shot": "steam burst, slow scoop", "audio": "ambient", "voiceover": "6 Stunden. Ein Topf."}],
  "carousel_slides": [{"n": 1, "image": "hero shot, 3:4", "headline": "..."}, {"n": 2, "...": "..."}],
  "thumbnail_text": "max 3 words",
  "hashtags": ["kacchibiryani", "berlinfood"],
  "topic_tag": "Berlin Food",
  "audio_choice": {"type": "original | platform_library", "description": "...", "licence_note": "..."},
  "alt_text": "describes the image for screen readers, includes 'Kacchi Biryani Berlin'",
  "cta": "...",
  "label": "Werbung | null",
  "checks": {"greeting_review_needed": false, "price_shown_incl_vat": true, "people_consent_needed": true}
}
```

- Fill `carousel_slides` only for carousels and albums, and `script` only for video formats.
- Text-first formats (Threads, X, LinkedIn, Reddit) need `caption`, `first_line` and a suggested image, if any.

## 4. Prompt templates

**System prompt** (one per writer agent):

```
You write social-media content for Dhaka Kacchi, a Bangladeshi kacchi-biryani restaurant in Berlin.
Signature: raw-marinated mutton and aromatic rice slow-cooked together under a sealed lid (dum), the Old Dhaka way.
Voice: warm, proud, generous host; food first; honest prices; never mocking other cuisines.
You receive one BRIEF (JSON). Follow it exactly: platform, format, length, language order, hook, pillar, hashtags,
audio rule and posting window are already decided from data. Your job is the words and the shot plan.
Hard rules:
- Every caption contains "Kacchi" and "Berlin".
- German first.
- Use the greeting text exactly as given, in its script.
- Never use anything in brief.do_not.
- Prices are total prices including VAT.
- No superlatives you cannot prove.
- "Halal" only if the brief says the restaurant is certified, and then name the certifier.
- No chart music.
- Influencer, discount-code or free-product posts start with "Werbung".
Return only the OUTPUT JSON described in the guide.
```

**User prompt per brief:** `BRIEF:\n<the items[] entry as JSON>\nDAY CONTEXT:\n<the matching day_themes entry>`

Use one model call per brief, temperature 0.7–0.9 for captions and 0.3 for the checker. A strong multilingual model
is needed for Bengali, Arabic, Turkish, Persian and similar scripts. Send anything with
`needs_native_review: true` to a person.

## 5. The checker agent (run on every output before a person sees it)

Reject the output and send it back to the writer if any check fails:

1. **Format:** length, ratio, slide count and hashtag count are within the brief's `media` limits. The Threads topic
   tag has no "#". Instagram has at most 5 hashtags.
2. **Brand words:** "Kacchi" and "Berlin" are in the caption, and the first line is at most 60 characters.
3. **Language:** the language order matches `languages[]`. The greeting is byte-identical to the brief.
4. **Legal (Germany):**
   - prices include VAT;
   - discounts state the 30-day lowest price;
   - no "der beste" or "Nr. 1";
   - no health claims;
   - "halal" only with a certifier;
   - "Werbung" for paid, gifted or discount-code content;
   - people on camera need consent.
5. **Tone:** if `day_themes.solemn_today` is not empty, no celebratory sales wording.
6. **Audio:** original audio or the platform's own commercial library, and no single track reused across platforms.
   A YouTube Short over 60 s uses only original audio or the YouTube Audio Library.
7. **Originality:** the plan uses the restaurant's own footage. No other creators' clips and no watermarks.

## 6. Planning shoots (one shoot, many posts)

- **Group the plan's items by pillar.** One dum-reveal shoot can feed the Instagram Reel, TikTok, YouTube Short,
  Facebook Reel and a carousel.
- **Film each format natively:**
  - vertical 9:16 for Reels, TikTok and Shorts;
  - 3:4 stills for Instagram feed and carousels;
  - 16:9 for the YouTube long film.
- **Export each platform's file separately** with that platform's audio bed. Never upload a TikTok export with its
  watermark to Instagram.
- **Capture clean sound:** seal break, sizzle, scoop. Original sound performs best in our data (+0.24 vs +0.16 for
  licensed tracks on TikTok).
- **Light warm (about 2700 K)** and keep the saffron and rice colours true.

## 7. Choosing 10, 15 or 30 days

`--days 10` gives about 78 briefs and `--days 30` about 235. A small team usually films twice a week. Generate 15
days, film the next 3–4 days' pillars in one session, and regenerate weekly, because occasions, audiences and
performance data update every Sunday.

## 8. Where each rule comes from

- **Platform and legal research:** `core.content_priors`, plus the October 2026 research on music licensing (GEMA,
  TikTok CML, Meta Sound Collection), YouTube Shorts Content ID, Medienanstalten ad labelling, PAngV and UWG.
- **Our own data:**
  - `marts.content_feature_performance`: lift per topic, cue, language and length per platform;
  - `marts.posting_time_performance`: the hour barely matters, under ±4 %;
  - `marts.audio_performance`: TikTok sounds;
  - `marts.trending_hashtags`.
- **Rules file:** `config/content/playbook.yaml`. Change the weights, cadence or hooks there and regenerate.
