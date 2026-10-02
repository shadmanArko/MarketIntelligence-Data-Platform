with src as {{ raw_entity('tiktok', 'profile', ok_only=false) }}
select observation_id, run_id, fetched_at, natural_key as handle,
       (payload ->> 'exists')::boolean as exists, payload ->> 'via' as discovered_via,
       (payload ->> 'business_id')::uuid as seed_business_id,
       payload ->> 'channel_id' as platform_account_id, payload ->> 'uploader' as display_name,
       {{ clean_text("payload ->> 'description'") }} as bio,
       (payload ->> 'channel_follower_count')::bigint as followers,
       jsonb_array_length(ops.jarr(payload -> 'videos')) as videos_listed,
       payload -> 'videos' as videos
from src
