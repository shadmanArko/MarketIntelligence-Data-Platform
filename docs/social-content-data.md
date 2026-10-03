# Social content, audiences and occasions — what is collected and where it lands

Goal: a clean, versioned dataset to learn *which content, in which language, for which community, on which
platform, at which time and occasion* performs — and which topics are rising — for Dhaka Kacchi in Berlin.

## Sources

| Source (connector / dataset) | What | Access | Refresh |
|---|---|---|---|
| `tiktok` | 506 Berlin restaurant accounts, 36k videos: views, likes, comments, shares, saves, sound, caption | public (yt-dlp) | manual |
| `reddit_archive` | Every post in 31 subreddits (r/berlin, r/germany, r/de, r/Kochen, r/biryani, r/IndianFood, r/bangladesh, r/arabs, r/TurkishFood, r/PersianFood, r/food, r/FoodPorn, ...) since 2019–2024: title, text, flair, format, score + comments at ~36 h | Arctic Shift archive (free) | weekly, last 3 months |
| `youtube` | Videos / Shorts / channels for 229 queries (Berlin food, biryani, every community dish in its own script, occasions), comments on tier-1 videos | YouTube Data API (free key) | weekly stats snapshot + weekly recent searches |
| `instagram_graph` | Competitor profiles + posts, hashtag media | Meta App Review pending | weekly once approved |
| `first_party` | Dhaka Kacchi's own Instagram / Facebook / Threads posts with reach, saves, shares | read-only warehouse | weekly |
| `wikipedia` | Daily page views since 2015 for 100+ dishes and occasions in 27 languages | free | weekly |
| `berlin_events` | Street festivals, Christmas markets (berlin.de open data) | free | weekly |
| dataset `afs_population` | Berlin residents by citizenship (every country) and migration background per district and LOR planning area, half-yearly | Amt für Statistik (open) | half-yearly |
| dataset `occasions` | 2015–2030 occasion calendar for 38 communities (python-holidays + rules) and Berlin iftar / suhoor times | computed | on taxonomy change |
| dataset `wikidata_dishes` | 952 rice dishes, 10k names in 44 languages | Wikidata (CC0) | quarterly |
| seed `content_priors` | 56 published platform rules / benchmarks (algorithm signals, formats, times, what to avoid) with source and evidence strength | research 2026-10 | manual |

Curated truth: `config/taxonomies/communities.yaml` (communities, languages, scripts, dishes, greetings),
`config/taxonomies/occasions.yaml` (occasion meaning, lead time, keywords), `config/keywords/social_content.yaml`
(search queries and format cues).

## Tables

| Table | Grain | Use |
|---|---|---|
| `core.post` | post / video (Instagram, TikTok, Reddit, YouTube) | text, format, duration, hashtags, context (account / subreddit / channel) |
| `core.post_metrics_snapshot` | post × observation | views, likes / score, comments, shares, saves, age |
| `core.content_tag` | post × tag | dishes, communities, occasions, format cues (`mip enrich content`) |
| `ops.text_language` | text | detected language (42 languages) |
| `core.community_audience` | release × community × area | residents per community, Berlin / district / LOR, share |
| `core.occasion_day` | day × community × occasion | meaning, tone, lead window, greeting, iftar / suhoor |
| `marts.content_performance` | post | performance normalised within peer (percentile, lift vs median, viral flag) |
| `marts.posting_time_performance` | platform × format × weekday × hour | when posting works (peer-normalised) |
| `marts.content_feature_performance` | platform × tag | which dishes / cues / languages / lengths beat the peer baseline |
| `marts.topic_trends_weekly` | week × tag × platform | momentum: posts per week, 4-week vs 12-week growth |
| `marts.occasion_content_calendar` | day × community × occasion (next 15 months) | what to post when, in which language, bridging which dish, for how many people where |
| `ml.feature_content` | mature post | leakage-free features + labels; exported with `mip ml export content_features` |

## Labels (how "it worked" is measured)

Different platforms and account sizes are not comparable in raw numbers, so every post is compared with its own
peer group (the same account, channel or subreddit):

- `label_log_perf` = ln(perf + 1), with perf = views (TikTok, YouTube), likes + comments (Instagram), score (Reddit)
- `label_lift_vs_prior` = label_log_perf minus the mean of the peer's *earlier* posts (no look-ahead)
- `label_pct_in_peer`, `label_viral_in_peer` (top 10 % of the peer's posts)

## Not possible / not collected

- LinkedIn: no API for other companies' content. X: paid only. Facebook pages of others: Meta App Review.
- Private accounts, private groups, DMs: never.
- Commenter / author identities: salted hashes only.
