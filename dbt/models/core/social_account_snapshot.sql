select md5('instagram:' || handle)::uuid as account_id, 'instagram' as platform, fetched_at as observed_at,
       followers, following, post_count
from {{ ref('stg_instagram__account') }} where followers is not null
union all
select md5('tiktok:' || handle)::uuid, 'tiktok', fetched_at, followers, null, videos_listed
from {{ ref('stg_tiktok__profile') }} where exists
