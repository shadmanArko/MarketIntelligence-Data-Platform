-- Topic momentum per ISO week: how often each dish / community / occasion / cue / hashtag appears in new posts,
-- and how those posts perform. growth_4w = posts in the last 4 weeks vs the 12 weeks before (per week).
with t as (
  select ct.tag_type, ct.tag_id, p.platform, p.posted_at, cp.perf_lift_vs_peer
  from {{ ref('content_tag') }} ct join {{ ref('post') }} p using (post_id)
  left join {{ ref('content_performance') }} cp using (post_id)
  union all
  select 'hashtag', h, p.platform, p.posted_at, cp.perf_lift_vs_peer
  from {{ ref('post') }} p cross join unnest(p.hashtags) h left join {{ ref('content_performance') }} cp using (post_id)
),
w as (
  select tag_type, tag_id, platform, date_trunc('week', posted_at)::date as week, count(*) as posts,
         avg(perf_lift_vs_peer) as mean_lift
  from t where posted_at >= now() - interval '3 years' group by 1, 2, 3, 4
)
select w.*,
       sum(posts) over (partition by tag_type, tag_id, platform order by week
                        range between interval '3 weeks' preceding and current row) / 4.0 as posts_per_week_4w,
       coalesce(sum(posts) over (partition by tag_type, tag_id, platform order by week
                        range between interval '15 weeks' preceding and interval '4 weeks' preceding), 0) / 12.0
         as posts_per_week_prev_12w,
       (sum(posts) over (partition by tag_type, tag_id, platform order by week
                         range between interval '3 weeks' preceding and current row) / 4.0 + 1)
       / (coalesce(sum(posts) over (partition by tag_type, tag_id, platform order by week
                           range between interval '15 weeks' preceding and interval '4 weeks' preceding), 0) / 12.0 + 1)
         as growth_4w
from w
