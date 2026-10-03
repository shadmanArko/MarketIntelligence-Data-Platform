{{ config(indexes=[{'columns': ['post_id'], 'unique': True}, {'columns': ['platform', 'peer_group']}]) }}
-- Post performance on every platform, normalised against its own peer group so that a small restaurant account,
-- a big creator and a subreddit are comparable.
--   perf_metric   views (TikTok, YouTube), likes + comments (Instagram), score (Reddit)
--   peer_group    the account / channel, or the subreddit for Reddit
--   perf_pct_in_peer   percentile of perf_metric among the peer group's mature posts (0..1)
--   perf_lift_vs_peer  ln((perf + 1) / (peer median + 1)); > 0 = better than usual for that peer
-- Posts younger than var('min_post_age_h', 72) h are not mature (Reddit: mature = archive's second read).
{% set min_age = var('min_post_age_h', 72) %}
with m as (
  select distinct on (post_id) * from {{ ref('post_metrics_snapshot') }} order by post_id, observed_at desc
),
f as (
  select distinct on (account_id) account_id, followers from {{ ref('social_account_snapshot') }}
  where followers is not null order by account_id, observed_at desc
),
p as (
  select po.post_id, po.platform, po.account_id, po.handle, po.context, sa.business_id, po.posted_at, po.post_type,
         po.duration_s, po.title_length, po.caption_length, cardinality(po.hashtags) as hashtag_count,
         cardinality(po.emojis) as emoji_count, po.audio_title, m.likes, m.comments, m.views, m.shares, m.saves,
         m.post_age_hours, f.followers,
         coalesce(po.account_id::text, po.context) as peer_group,
         case po.platform when 'reddit' then m.likes
                          when 'instagram' then coalesce(m.likes, 0) + coalesce(m.comments, 0)
                          else m.views end as perf_metric,
         (coalesce(m.likes, 0) + coalesce(m.comments, 0) + coalesce(m.shares, 0) + coalesce(m.saves, 0))::float8
           / nullif(f.followers, 0) as engagement_rate,
         case when po.platform = 'reddit' then m.post_age_hours >= 24 else m.post_age_hours >= {{ min_age }} end as mature
  from {{ ref('post') }} po join m using (post_id) left join f using (account_id)
  left join {{ ref('social_account') }} sa using (account_id)
),
peer as (
  select platform, peer_group, count(*) as peer_posts,
         percentile_cont(0.5) within group (order by perf_metric) as peer_median
  from p where mature and perf_metric is not null group by 1, 2
)
select p.*, peer.peer_posts, peer.peer_median,
       case when p.mature and p.perf_metric is not null then
         percent_rank() over (partition by p.platform, p.peer_group, p.mature, (p.perf_metric is not null)
                              order by p.perf_metric) end as perf_pct_in_peer,
       case when p.mature and p.perf_metric is not null then
         ln((p.perf_metric + 1)::float8 / (peer.peer_median + 1)) end as perf_lift_vs_peer,
       case when p.mature and p.perf_metric is not null and peer.peer_posts >= 10 then
         percent_rank() over (partition by p.platform, p.peer_group, p.mature, (p.perf_metric is not null)
                              order by p.perf_metric) >= 0.9 end as is_viral_in_peer,
       -- backwards-compatible names (account-level percentile on views)
       case when p.mature and p.views is not null then
         percent_rank() over (partition by p.account_id, p.mature, (p.views is not null) order by p.views) end
         as views_pct_rank_in_account,
       extract(isodow from p.posted_at at time zone '{{ var("local_tz") }}') as posted_weekday_berlin,
       extract(hour from p.posted_at at time zone '{{ var("local_tz") }}')   as posted_hour_berlin
from p left join peer using (platform, peer_group)
