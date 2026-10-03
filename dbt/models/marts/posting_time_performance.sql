-- When posting works, per platform and format: Berlin weekday x hour, relative to each peer's usual performance.
-- Uses perf_lift_vs_peer (0 = the account's / subreddit's median), so big and small accounts count equally.
select platform, post_type, posted_weekday_berlin::int as iso_weekday, posted_hour_berlin::int as hour_berlin,
       count(*) as posts, count(distinct peer_group) as peers,
       percentile_cont(0.5) within group (order by perf_lift_vs_peer) as median_lift,
       avg(perf_pct_in_peer) as mean_pct_in_peer,
       avg(is_viral_in_peer::int) as viral_share
from {{ ref('content_performance') }}
where mature and perf_lift_vs_peer is not null and posted_at >= now() - interval '3 years'
group by grouping sets ((platform, post_type, posted_weekday_berlin, posted_hour_berlin),
                        (platform, posted_weekday_berlin, posted_hour_berlin))
having count(*) >= 20
