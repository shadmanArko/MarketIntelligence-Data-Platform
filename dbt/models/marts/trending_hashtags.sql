-- Hashtags by use and engagement over recent posts (captions) and hashtag search ranks.
with tags as (
  select unnest(po.hashtags) as hashtag, po.platform, po.posted_at, cp.engagement_rate, cp.views
  from {{ ref('post') }} po left join {{ ref('content_performance') }} cp using (post_id)
)
select hashtag, platform,
       count(*) as posts, count(*) filter (where posted_at > now() - interval '30 days') as posts_30d,
       avg(engagement_rate) as mean_engagement_rate, percentile_cont(0.5) within group (order by views) as median_views
from tags group by 1, 2 having count(*) >= 3
