{{ config(indexes=[{'columns': ['account_id'], 'unique': True}]) }}
-- One account on one platform, latest attributes; business link from ops.social_assignment.
with ig as (
  select distinct on (handle) 'instagram' as platform, handle, platform_account_id, display_name, bio, website,
         is_business, profile_image_url, fetched_at
  from {{ ref('stg_instagram__account') }} order by handle, fetched_at desc
),
tt as (
  select distinct on (handle) 'tiktok', handle, platform_account_id, display_name, bio, null::text, exists,
         null::text, fetched_at
  from {{ ref('stg_tiktok__profile') }} order by handle, fetched_at desc
),
u as (select * from ig union all select * from tt)
select md5(u.platform || ':' || u.handle)::uuid as account_id, u.*, sa.business_id, sa.decision as link_decision,
       sa.score as link_score
from u left join ops.social_assignment sa on sa.account_key = u.platform || ':' || u.handle
