-- Post x observation: likes, comments, views, shares, saves, and the post's age at that moment.
with u as (
  select 'instagram' as platform, post_platform_id, fetched_at, likes, comments, null::bigint as views,
         null::bigint as shares, null::bigint as saves, posted_at
  from {{ ref('stg_instagram__media') }}
  union all
  select 'tiktok', post_platform_id, fetched_at, likes, comments, views, shares, saves, posted_at
  from {{ ref('stg_tiktok__video') }}
)
select distinct on (platform, post_platform_id, fetched_at)
  md5(platform || ':' || post_platform_id)::uuid as post_id, platform, fetched_at as observed_at,
  likes, comments, views, shares, saves,
  likes is null and platform = 'instagram' as likes_hidden,
  round((extract(epoch from fetched_at - posted_at) / 3600)::numeric, 1) as post_age_hours
from u order by platform, post_platform_id, fetched_at, (views is null)
