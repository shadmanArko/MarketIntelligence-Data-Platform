-- Instagram media from Business Discovery (per account) and Hashtag Search (top / recent).
with bd as {{ raw_entity('instagram_graph', 'media_page') }},
ht as {{ raw_entity('instagram_graph', 'hashtag_media') }},
src as (
  select s.observation_id, s.fetched_at, s.payload ->> 'username' as handle, m.value as v, 'business_discovery' as via
  from bd s, jsonb_array_elements(ops.jarr(s.payload -> 'media')) m
  union all
  select s.observation_id, s.fetched_at, null, m.value, 'hashtag:' || (s.payload ->> 'hashtag') || ':' || (s.payload ->> 'edge')
  from ht s, jsonb_array_elements(ops.jarr(s.payload -> 'data')) m
)
select observation_id, fetched_at, coalesce(handle, v ->> 'username') as handle, via,
       v ->> 'id' as post_platform_id, {{ clean_text("v ->> 'caption'") }} as caption,
       (v ->> 'timestamp')::timestamptz as posted_at,
       lower(coalesce(v ->> 'media_product_type', '') || ':' || coalesce(v ->> 'media_type', '')) as post_type,
       (v ->> 'like_count')::bigint as likes, (v ->> 'comments_count')::bigint as comments,
       v ->> 'permalink' as permalink, coalesce(v ->> 'thumbnail_url', v ->> 'media_url') as thumbnail_url, v
from src
