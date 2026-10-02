-- Videos from profile listings (flat) and per-video detail; the detail wins where both exist.
with listed as (
  select p.observation_id, p.fetched_at, p.handle, v.value as v, 'listing' as via
  from {{ ref('stg_tiktok__profile') }} p, jsonb_array_elements(ops.jarr(p.videos)) v
),
detail as (
  select observation_id, fetched_at, payload ->> 'handle' as handle, payload as v, 'detail' as via
  from {{ raw_entity('tiktok', 'video') }} s
),
u as (select * from listed union all select * from detail)
select observation_id, fetched_at, handle, via,
       v ->> 'id' as post_platform_id,
       {{ clean_text("coalesce(v ->> 'description', v ->> 'title')") }} as caption,
       case when v ->> 'timestamp' ~ '^\d+$' then to_timestamp((v ->> 'timestamp')::bigint) end as posted_at,
       (v ->> 'duration')::float8::integer as duration_s,
       (v ->> 'view_count')::bigint as views, (v ->> 'like_count')::bigint as likes,
       (v ->> 'comment_count')::bigint as comments, (v ->> 'repost_count')::bigint as shares,
       (v ->> 'save_count')::bigint as saves,
       coalesce(v ->> 'track', v #>> '{music,title}') as audio_title, v ->> 'artist' as audio_artist,
       v ->> 'webpage_url' as permalink, v ->> 'thumbnail' as thumbnail_url, v
from u where v ->> 'id' is not null
