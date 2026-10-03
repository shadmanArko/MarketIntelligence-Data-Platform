{{ config(indexes=[{'columns': ['post_id'], 'unique': True}, {'columns': ['account_id']},
                   {'columns': ['platform', 'posted_at']}]) }}
-- One post / video (immutable attributes) across platforms. Moving numbers are in post_metrics_snapshot.
--   context      where it was published: subreddit, YouTube channel, own handle
--   caption      body text (Instagram/TikTok caption, Reddit selftext, YouTube description); title separate
with u as (
  select 'instagram' as platform, post_platform_id, handle, null::text as title, caption, posted_at, post_type,
         null::integer as duration_s, null::text as audio_title, permalink, thumbnail_url, fetched_at,
         handle as context, null::text[] as tags, null::text as declared_language, null::text as category
  from {{ ref('stg_instagram__media') }}
  union all
  select 'tiktok', post_platform_id, handle, null, caption, posted_at, 'video', duration_s, audio_title, permalink,
         thumbnail_url, fetched_at, handle, null, null, null
  from {{ ref('stg_tiktok__video') }}
  union all
  select 'reddit', post_platform_id, null, title, selftext, posted_at, post_type, null, null, permalink, null,
         fetched_at, 'r/' || subreddit, null, null, flair
  from {{ ref('stg_reddit__post') }}
  union all
  select 'youtube', post_platform_id, channel_id, title, description, posted_at,
         case when duration_s <= 180 then 'short_or_clip' else 'video' end, duration_s, null, permalink,
         thumbnail_url, fetched_at, channel_title, tags, declared_language, category_id
  from {{ ref('stg_youtube__video') }}
)
select distinct on (platform, post_platform_id)
  md5(platform || ':' || post_platform_id)::uuid as post_id, platform, post_platform_id,
  case when handle is not null then md5(platform || ':' || lower(handle))::uuid end as account_id, handle, context,
  title, caption, posted_at, post_type, duration_s, audio_title, permalink, thumbnail_url, tags, declared_language,
  category,
  array(select lower(m[1]) from regexp_matches(coalesce(title, '') || ' ' || coalesce(caption, ''), '#([[:alnum:]_äöüß]+)', 'g') m) as hashtags,
  array(select lower(m[1]) from regexp_matches(coalesce(caption, ''), '@([[:alnum:]_.]+)', 'g') m) as mentions,
  array(select m[1] from regexp_matches(coalesce(title, '') || ' ' || coalesce(caption, ''), '([\U0001F300-\U0001FAFF☀-➿])', 'g') m) as emojis,
  length(caption) as caption_length, length(title) as title_length
from u order by platform, post_platform_id, (coalesce(caption, title) is null), fetched_at desc
