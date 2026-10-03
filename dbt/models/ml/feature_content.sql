{{ config(indexes=[{'columns': ['post_id'], 'unique': True}]) }}
-- One row per mature post on every platform: what was knowable when it was published (format, length, text cues,
-- dishes, communities, occasions, language, timing, the peer's track record so far) and how it performed.
-- Leakage-free: peer baselines use only the peer's EARLIER posts; labels come from the latest metrics snapshot.
--   label_log_perf        ln(perf_metric + 1)
--   label_lift_vs_prior   label_log_perf - mean ln(perf + 1) of the peer's previous posts (needs >= 5 earlier posts)
--   label_pct_in_peer / label_viral_in_peer   percentile / top-10 % within the peer group (all mature posts)
{% set as_of = var('as_of', none) %}
{% set as_of_sql = "'" ~ as_of ~ "'::timestamptz" if as_of else "now()" %}
with cp as (
  select * from {{ ref('content_performance') }}
  where posted_at <= {{ as_of_sql }} and perf_metric is not null and mature
),
hist as (
  select post_id,
         avg(ln(perf_metric + 1)) over w as peer_prior_mean_log_perf,
         count(*) over w as peer_prior_posts,
         extract(epoch from posted_at - lag(posted_at) over (partition by platform, peer_group order by posted_at))
           / 3600 as hours_since_peer_prev_post
  from cp
  window w as (partition by platform, peer_group order by posted_at rows between unbounded preceding and 1 preceding)
),
tags as (
  select post_id,
         array_agg(distinct tag_id) filter (where tag_type = 'cue') as cues,
         array_agg(distinct tag_id) filter (where tag_type = 'dish') as dishes,
         array_agg(distinct tag_id) filter (where tag_type = 'community') as communities,
         array_agg(distinct tag_id) filter (where tag_type = 'occasion') as occasions,
         array_agg(distinct tag_id) filter (where tag_type = 'rice_dish') as rice_dishes
  from {{ ref('content_tag') }} group by 1
),
next_occ as (   -- the nearest upcoming occasion of any community at posting time (Berlin date)
  select cp.post_id,
         min(o.day - (cp.posted_at at time zone '{{ var("local_tz") }}')::date) as days_to_next_occasion,
         (array_agg(o.occasion_type order by o.day))[1] as next_occasion_type
  from cp join {{ ref('occasion_day') }} o
    on o.day between (cp.posted_at at time zone '{{ var("local_tz") }}')::date
                 and (cp.posted_at at time zone '{{ var("local_tz") }}')::date + 30
   and o.occasion_type not in ('payday', 'national_day', 'remembrance_day', 'semester_start')
  group by 1
),
in_occ as (
  select cp.post_id, array_agg(distinct o.occasion_type) as occasions_on_day
  from cp join {{ ref('occasion_day') }} o on o.day = (cp.posted_at at time zone '{{ var("local_tz") }}')::date
   and o.community_id in ('all', 'german', 'turkish', 'bangladeshi', 'indian', 'syrian', 'arab', 'vietnamese')
  group by 1
)
select cp.post_id, cp.platform, cp.peer_group, {{ as_of_sql }} as as_of, p.posted_at,
       -- format
       cp.post_type, cp.duration_s, cp.title_length, cp.caption_length, cp.hashtag_count, cp.emoji_count,
       p.audio_title is not null as has_audio_title, cardinality(p.mentions) as mention_count,
       p.title ~ '\?' or p.caption ~ '^[^.!]{0,120}\?' as asks_question,
       p.title ~ '\d' as title_has_number, p.title ~ '[€$]|\m(eur|euro)\M' as title_has_price,
       case when length(p.title) > 0 then length(regexp_replace(p.title, '[^A-ZÄÖÜ]', '', 'g'))::float8
            / nullif(length(regexp_replace(p.title, '[^[:alpha:]]', '', 'g')), 0) end as title_caps_ratio,
       l.lang as language, l.confidence as language_confidence, p.declared_language,
       -- content
       coalesce(t.cues, '{}') as cues, coalesce(t.dishes, '{}') as dishes, coalesce(t.communities, '{}') as communities,
       coalesce(t.occasions, '{}') as occasions_mentioned, coalesce(t.rice_dishes, '{}') as rice_dishes,
       -- timing (Berlin)
       cp.posted_weekday_berlin::int as iso_weekday, cp.posted_hour_berlin::int as hour_berlin,
       cp.posted_weekday_berlin >= 6 as is_weekend, extract(month from p.posted_at)::int as month,
       coalesce(io.occasions_on_day, '{}') as occasions_on_day, no.days_to_next_occasion, no.next_occasion_type,
       h.hours_since_peer_prev_post,
       -- peer context known at posting time
       cp.followers, h.peer_prior_posts, h.peer_prior_mean_log_perf,
       -- labels
       ln(cp.perf_metric + 1) as label_log_perf,
       case when h.peer_prior_posts >= 5 then ln(cp.perf_metric + 1) - h.peer_prior_mean_log_perf end as label_lift_vs_prior,
       cp.perf_pct_in_peer as label_pct_in_peer, cp.is_viral_in_peer as label_viral_in_peer,
       cp.likes, cp.comments, cp.views, cp.shares, cp.saves, cp.post_age_hours as label_age_hours
from cp
join {{ ref('post') }} p using (post_id)
join hist h using (post_id)
left join tags t using (post_id)
left join ops.text_language l on l.text_kind = 'post' and l.text_id = cp.post_id::text
left join next_occ no using (post_id)
left join in_occ io using (post_id)
