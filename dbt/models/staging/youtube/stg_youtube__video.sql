-- YouTube video x observation (every statistics read is a snapshot).
with v as (
  select o.observation_id, o.fetched_at, (o.payload ->> 'tier')::int as query_tier, x.value as v
  from {{ raw_entity('youtube', 'videos') }} o, jsonb_array_elements(ops.jarr(o.payload -> 'items')) x
)
select observation_id, fetched_at,
  v ->> 'id' as post_platform_id,
  v #>> '{snippet,channelId}' as channel_id,
  {{ clean_text("v #>> '{snippet,channelTitle}'") }} as channel_title,
  {{ clean_text("v #>> '{snippet,title}'") }} as title,
  {{ clean_text("v #>> '{snippet,description}'") }} as description,
  array(select jsonb_array_elements_text(ops.jarr(v #> '{snippet,tags}'))) as tags,
  (v #>> '{snippet,publishedAt}')::timestamptz as posted_at,
  v #>> '{snippet,categoryId}' as category_id,
  coalesce(v #>> '{snippet,defaultAudioLanguage}', v #>> '{snippet,defaultLanguage}') as declared_language,
  v #>> '{snippet,liveBroadcastContent}' as live_content,
  v #>> '{contentDetails,duration}' as duration_iso,
  (extract(epoch from (v #>> '{contentDetails,duration}')::interval))::int as duration_s,
  v #>> '{contentDetails,definition}' as definition,
  (v #>> '{contentDetails,caption}')::boolean as has_captions,
  (v #>> '{contentDetails,licensedContent}')::boolean as licensed_content,
  v #>> '{status,madeForKids}' = 'true' as made_for_kids,
  (v #>> '{statistics,viewCount}')::bigint as views,
  (v #>> '{statistics,likeCount}')::bigint as likes,
  (v #>> '{statistics,commentCount}')::bigint as comments,
  array(select regexp_replace(t, '^https?://en.wikipedia.org/wiki/', '')
        from jsonb_array_elements_text(ops.jarr(v #> '{topicDetails,topicCategories}')) t) as topics,
  v #>> '{snippet,thumbnails,high,url}' as thumbnail_url,
  'https://www.youtube.com/watch?v=' || (v ->> 'id') as permalink,
  query_tier
from v
where v ->> 'id' is not null
