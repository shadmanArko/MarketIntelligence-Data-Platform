-- Post performance per account. Engagement rate = (likes + comments + shares + saves) / followers at observation.
-- One-time-run caveat: posts younger than var('min_post_age_h', 72) h are excluded from the "mature" flags,
-- since a 2-day-old reel always looks weaker than a 2-month-old one.
{% set min_age = var('min_post_age_h', 72) %}
with m as (
  select distinct on (post_id) * from {{ ref('post_metrics_snapshot') }} order by post_id, observed_at desc
),
f as (
  select distinct on (account_id) account_id, followers from {{ ref('social_account_snapshot') }}
  where followers is not null order by account_id, observed_at desc
),
p as (
  select po.post_id, po.platform, po.account_id, po.handle, sa.business_id, po.posted_at, po.post_type, po.duration_s,
         po.caption_length, cardinality(po.hashtags) as hashtag_count, cardinality(po.emojis) as emoji_count,
         po.audio_title, m.likes, m.comments, m.views, m.shares, m.saves, m.post_age_hours, f.followers,
         (coalesce(m.likes, 0) + coalesce(m.comments, 0) + coalesce(m.shares, 0) + coalesce(m.saves, 0))::float8
           / nullif(f.followers, 0) as engagement_rate,
         m.post_age_hours >= {{ min_age }} as mature
  from {{ ref('post') }} po join m using (post_id) left join f using (account_id)
  left join {{ ref('social_account') }} sa using (account_id)
)
select p.*,
       -- viral = top 10 % of the account's own mature posts by views (account-normalised)
       case when mature and views is not null then
         percent_rank() over (partition by account_id, mature order by views) end as views_pct_rank_in_account,
       case when mature and views is not null then
         percent_rank() over (partition by account_id, mature order by views) >= 0.9 end as is_viral_in_account,
       extract(isodow from posted_at at time zone '{{ var("local_tz") }}') as posted_weekday_berlin,
       extract(hour from posted_at at time zone '{{ var("local_tz") }}')   as posted_hour_berlin
from p
