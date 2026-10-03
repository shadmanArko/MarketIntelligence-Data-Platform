-- YouTube channel x observation.
with c as (
  select o.observation_id, o.fetched_at, o.payload ->> 'origin' as origin, x.value as v
  from {{ raw_entity('youtube', 'channels') }} o, jsonb_array_elements(ops.jarr(o.payload -> 'items')) x
)
select observation_id, fetched_at, origin,
  v ->> 'id' as channel_id,
  {{ clean_text("v #>> '{snippet,title}'") }} as title,
  lower(nullif(v #>> '{snippet,customUrl}', '')) as handle,
  {{ clean_text("v #>> '{snippet,description}'") }} as description,
  v #>> '{snippet,country}' as country,
  v #>> '{snippet,defaultLanguage}' as default_language,
  (v #>> '{snippet,publishedAt}')::timestamptz as created_at,
  (v #>> '{statistics,subscriberCount}')::bigint as subscribers,
  coalesce((v #>> '{statistics,hiddenSubscriberCount}')::boolean, false) as subscribers_hidden,
  (v #>> '{statistics,viewCount}')::bigint as total_views,
  (v #>> '{statistics,videoCount}')::bigint as video_count,
  v #>> '{contentDetails,relatedPlaylists,uploads}' as uploads_playlist,
  array(select regexp_replace(t, '^https?://en.wikipedia.org/wiki/', '')
        from jsonb_array_elements_text(ops.jarr(v #> '{topicDetails,topicCategories}')) t) as topics
from c where v ->> 'id' is not null
