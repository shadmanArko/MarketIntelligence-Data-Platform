-- Which query surfaced which video, at which rank, when: search visibility over time.
select o.observation_id, o.fetched_at, o.payload ->> 'query' as query, o.payload ->> 'region' as region,
       o.payload ->> 'lang' as lang, o.payload ->> 'order' as search_order, (o.payload ->> 'tier')::int as tier,
       o.payload ->> 'origin' as query_origin,
       x.ordinality::int as rank, x.value #>> '{id,videoId}' as video_id, x.value #>> '{snippet,channelId}' as channel_id
from {{ raw_entity('youtube', 'search') }} o, jsonb_array_elements(ops.jarr(o.payload -> 'items')) with ordinality x
where x.value #>> '{id,videoId}' is not null
