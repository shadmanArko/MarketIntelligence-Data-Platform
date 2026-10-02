with src as {{ raw_entity('instagram_graph', 'account', ok_only=false) }}
select observation_id, run_id, fetched_at, natural_key as handle,
       not coalesce((payload ->> 'not_business')::boolean, false) as is_business,
       payload ->> 'id' as platform_account_id, payload ->> 'name' as display_name,
       {{ clean_text("payload ->> 'biography'") }} as bio, {{ clean_url("payload ->> 'website'") }} as website,
       (payload ->> 'followers_count')::bigint as followers, (payload ->> 'follows_count')::bigint as following,
       (payload ->> 'media_count')::bigint as post_count, payload ->> 'profile_picture_url' as profile_image_url,
       (request_meta ->> 'business_id')::uuid as seed_business_id
from src
