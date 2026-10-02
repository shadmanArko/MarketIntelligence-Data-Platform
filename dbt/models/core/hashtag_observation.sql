-- Hashtag x post x rank x observation (Instagram hashtag search, top + recent).
select split_part(via, ':', 2) as hashtag, split_part(via, ':', 3) as edge, 'instagram' as platform,
       md5('instagram:' || post_platform_id)::uuid as post_id,
       row_number() over (partition by via, observation_id order by posted_at desc) as rank, fetched_at as observed_at
from {{ ref('stg_instagram__media') }} where via like 'hashtag:%'
