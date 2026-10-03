-- What content works: for every tag (dish, community, occasion, format cue, language, format, length bucket) and
-- platform, how posts with it perform against their own peer baseline, and against posts without it.
with cp as (
  select * from {{ ref('content_performance') }}
  where mature and perf_lift_vs_peer is not null and posted_at >= now() - interval '3 years'
),
feat as (
  select post_id, tag_type, tag_id from {{ ref('content_tag') }}
  union all
  select post_id, 'language', lang from ops.text_language l join cp on cp.post_id::text = l.text_id
  where l.text_kind = 'post' and l.lang is not null and l.confidence >= 0.6
  union all
  select post_id, 'post_type', post_type from cp where post_type is not null
  union all
  select post_id, 'duration', case when duration_s < 15 then '<15s' when duration_s < 30 then '15-29s'
                                   when duration_s < 60 then '30-59s' when duration_s < 180 then '1-3min'
                                   when duration_s < 600 then '3-10min' else '10min+' end
  from cp where duration_s is not null
  union all
  select post_id, 'hashtags', case when hashtag_count = 0 then '0' when hashtag_count <= 3 then '1-3'
                                   when hashtag_count <= 5 then '4-5' when hashtag_count <= 10 then '6-10' else '11+' end
  from cp
),
base as (
  select platform, avg(perf_lift_vs_peer) as platform_mean_lift, count(*) as platform_posts from cp group by 1
)
select cp.platform, f.tag_type, f.tag_id, count(*) as posts, count(distinct cp.peer_group) as peers,
       percentile_cont(0.5) within group (order by cp.perf_lift_vs_peer) as median_lift,
       avg(cp.perf_lift_vs_peer) as mean_lift,
       avg(cp.perf_lift_vs_peer) - max(b.platform_mean_lift) as mean_lift_vs_platform,
       avg(cp.perf_pct_in_peer) as mean_pct_in_peer, avg(cp.is_viral_in_peer::int) as viral_share,
       stddev_samp(cp.perf_lift_vs_peer) / sqrt(count(*)) as lift_std_error,
       max(b.platform_posts) as platform_posts
from feat f join cp using (post_id) join base b on b.platform = cp.platform
group by 1, 2, 3 having count(*) >= 15
