-- Post x observation: likes / score, comments, views, shares, saves, and the post's age at that moment.
-- Reddit: score (upvotes - downvotes) is stored as likes; observed_at is the archive's second read.
with u as (
  select 'instagram' as platform, post_platform_id, fetched_at as observed_at, likes, comments, null::bigint as views,
         null::bigint as shares, null::bigint as saves, posted_at
  from {{ ref('stg_instagram__media') }}
  union all
  select 'tiktok', post_platform_id, fetched_at, likes, comments, views, shares, saves, posted_at
  from {{ ref('stg_tiktok__video') }}
  union all
  select 'reddit', post_platform_id, metrics_at, score, comments, null, crossposts, null, posted_at
  from {{ ref('stg_reddit__post') }}
  union all
  select 'youtube', post_platform_id, fetched_at, likes, comments, views, null, null, posted_at
  from {{ ref('stg_youtube__video') }}
)
select distinct on (platform, post_platform_id, observed_at)
  md5(platform || ':' || post_platform_id)::uuid as post_id, platform, observed_at,
  likes, comments, views, shares, saves,
  likes is null and platform in ('instagram', 'youtube') as likes_hidden,
  round((extract(epoch from observed_at - posted_at) / 3600)::numeric, 1) as post_age_hours
from u order by platform, post_platform_id, observed_at, (views is null)
