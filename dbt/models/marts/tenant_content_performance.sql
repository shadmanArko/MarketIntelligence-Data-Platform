{{ config(post_hook=[
  "alter table {{ this }} enable row level security",
  "drop policy if exists tenant_isolation on {{ this }}",
  "create policy tenant_isolation on {{ this }} using (tenant_id = current_setting('app.tenant_id', true))"]) }}
-- Dhaka Kacchi's own posts with their latest metrics, tags and language, scored against the account's own posts on
-- the same platform (the same peer logic as marts.content_performance for the market).
--   audience        reach where the platform reports it, otherwise impressions (Threads)
--   engagement      likes + comments + shares + saves
--   eng_rate        engagement / audience
--   pct_in_platform percentile of audience among this account's mature posts on that platform
with m as (
  select distinct on (post_id) * from {{ ref('tenant_social_metrics_snapshot') }} order by post_id, captured_at desc
),
t as (
  select text_id::uuid as post_id,
         array_agg(distinct tag_id) filter (where tag_type = 'cue') as cues,
         array_agg(distinct tag_id) filter (where tag_type in ('dish', 'rice_dish')) as dishes,
         array_agg(distinct tag_id) filter (where tag_type = 'community') as communities,
         array_agg(distinct tag_id) filter (where tag_type = 'occasion') as occasions
  from ops.content_tag where text_kind = 'own_post' group by 1
),
b as (
  select p.post_id, p.tenant_id, p.platform, p.content_type, p.posted_at, p.caption, p.permalink, p.caption_length,
         cardinality(p.hashtags) as hashtag_count, p.hashtags, p.posted_weekday_berlin::int as iso_weekday,
         p.posted_hour_berlin::int as hour_berlin, l.lang as language,
         m.reach, m.impressions, m.likes, m.comments, m.shares, m.saves, m.clicks, m.post_age_hours,
         coalesce(m.reach, m.impressions) as audience,
         coalesce(m.likes, 0) + coalesce(m.comments, 0) + coalesce(m.shares, 0) + coalesce(m.saves, 0) as engagement,
         m.post_age_hours >= 72 as mature,
         coalesce(t.cues, '{}') as cues, coalesce(t.dishes, '{}') as dishes, coalesce(t.communities, '{}') as communities,
         coalesce(t.occasions, '{}') as occasions
  from {{ ref('tenant_social_post') }} p
  left join m using (post_id)
  left join t using (post_id)
  left join ops.text_language l on l.text_kind = 'own_post' and l.text_id = p.post_id::text and l.confidence >= 0.5
)
select b.*,
       engagement::float8 / nullif(audience, 0) as eng_rate,
       case when mature and audience is not null then
         percent_rank() over (partition by platform, mature, (audience is not null) order by audience) end as pct_in_platform
from b
