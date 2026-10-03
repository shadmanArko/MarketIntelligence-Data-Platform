-- One row per Reddit post (latest archive read). Score / comments are Arctic Shift's second read (~1-2 days after
-- posting): a consistent early-performance label. Authors are already salted hashes.
with p as (
  select o.observation_id, o.fetched_at, x.value as v
  from {{ raw_entity('reddit_archive', 'posts_page') }} o, jsonb_array_elements(ops.jarr(o.payload -> 'posts')) x
)
select distinct on (v ->> 'id')
  observation_id, fetched_at,
  v ->> 'id' as post_platform_id,
  lower(v ->> 'subreddit') as subreddit,
  (v ->> 'subreddit_subscribers')::bigint as subreddit_subscribers,
  v ->> 'author' as author_hash,
  {{ clean_text("v ->> 'title'") }} as title,
  case when v ->> 'selftext' in ('[removed]', '[deleted]') then null else {{ clean_text("v ->> 'selftext'") }} end as selftext,
  {{ clean_text("v ->> 'link_flair_text'") }} as flair,
  to_timestamp((v ->> 'created_utc')::float8) as posted_at,
  to_timestamp(coalesce((v #>> '{_meta,retrieved_2nd_on}')::float8, (v ->> 'retrieved_on')::float8)) as metrics_at,
  (v #>> '{_meta,retrieved_2nd_on}') is not null as metrics_mature,
  (v ->> 'score')::bigint as score,
  (v ->> 'num_comments')::bigint as comments,
  (v ->> 'upvote_ratio')::float8 as upvote_ratio,
  (v ->> 'num_crossposts')::int as crossposts,
  case when (v ->> 'is_video')::boolean then 'video'
       when (v ->> 'is_gallery')::boolean then 'gallery'
       when v ->> 'post_hint' = 'image' or v ->> 'domain' in ('i.redd.it', 'i.imgur.com') then 'image'
       when (v ->> 'is_self')::boolean then 'text'
       when v ->> 'domain' ~ '(youtube\.com|youtu\.be|tiktok\.com|v\.redd\.it|instagram\.com)' then 'video_link'
       else 'link' end as post_type,
  {{ domain("v ->> 'url'") }} as link_domain,
  'https://www.reddit.com' || (v ->> 'permalink') as permalink,
  (v ->> 'over_18')::boolean as over_18,
  coalesce((v #>> '{_meta,was_deleted_later}')::boolean, false) as was_deleted_later,
  v #>> '{_meta,removal_type}' as removal_type,
  (v ->> 'is_original_content')::boolean as is_original_content,
  v ->> 'distinguished' as distinguished, (v ->> 'stickied')::boolean as stickied
from p
where v ->> 'id' is not null
order by v ->> 'id', fetched_at desc
