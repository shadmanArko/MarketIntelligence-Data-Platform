{{ config(indexes=[{'columns': ['post_id'], 'unique': True}, {'columns': ['account_id']}]) }}
-- One post (immutable attributes). Moving numbers are in post_metrics_snapshot.
with u as (
  select 'instagram' as platform, post_platform_id, handle, caption, posted_at, post_type, null::integer as duration_s,
         null::text as audio_title, permalink, thumbnail_url, fetched_at
  from {{ ref('stg_instagram__media') }}
  union all
  select 'tiktok', post_platform_id, handle, caption, posted_at, 'video', duration_s, audio_title, permalink,
         thumbnail_url, fetched_at
  from {{ ref('stg_tiktok__video') }}
)
select distinct on (platform, post_platform_id)
  md5(platform || ':' || post_platform_id)::uuid as post_id, platform, post_platform_id,
  case when handle is not null then md5(platform || ':' || lower(handle))::uuid end as account_id, handle,
  caption, posted_at, post_type, duration_s, audio_title, permalink, thumbnail_url,
  array(select lower(m[1]) from regexp_matches(coalesce(caption, ''), '#([[:alnum:]_äöüß]+)', 'g') m) as hashtags,
  array(select lower(m[1]) from regexp_matches(coalesce(caption, ''), '@([[:alnum:]_.]+)', 'g') m) as mentions,
  array(select m[1] from regexp_matches(coalesce(caption, ''), '([\U0001F300-\U0001FAFF☀-➿])', 'g') m) as emojis,
  length(caption) as caption_length
from u order by platform, post_platform_id, (caption is null), fetched_at desc
