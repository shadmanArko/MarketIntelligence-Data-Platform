{{ config(post_hook=[
  "alter table {{ this }} enable row level security",
  "drop policy if exists tenant_isolation on {{ this }}",
  "create policy tenant_isolation on {{ this }} using (tenant_id = current_setting('app.tenant_id', true))"]) }}
-- Own post x capture time: impressions, reach, likes, comments, shares, saves, clicks, post age at capture.
-- Metrics a platform does not report are NULL, not 0: Instagram returns no impressions, Threads no reach, and only
-- Facebook returns clicks (the warehouse and the exports store those as 0).
with u as (
  select md5(p.tenant_id || ':' || p.platform || ':' || p.external_id)::uuid as post_id, p.tenant_id, p.platform,
         p.posted_at, (s.value ->> 'captured_at')::timestamptz as captured_at,
         (s.value ->> 'impressions')::bigint as impressions, (s.value ->> 'reach')::bigint as reach,
         (s.value ->> 'likes')::bigint as likes, (s.value ->> 'comments')::bigint as comments,
         (s.value ->> 'shares')::bigint as shares, (s.value ->> 'saves')::bigint as saves,
         (s.value ->> 'clicks')::bigint as clicks, 'warehouse' as via
  from {{ ref('stg_first_party__own_post') }} p, jsonb_array_elements(ops.jarr(p.snapshots)) s
  union all
  select md5(tenant_id || ':' || platform || ':' || external_id)::uuid, tenant_id, platform, posted_at, captured_at,
         impressions, reach, likes, comments, shares, saves, clicks, 'export'
  from {{ ref('stg_first_party__export') }}
)
select distinct on (post_id, date_trunc('minute', captured_at))
       post_id, tenant_id, platform, captured_at,
       case when platform = 'threads' then null else reach end as reach,
       case when platform = 'instagram' then null else impressions end as impressions,
       likes, comments, shares, saves,
       case when platform = 'facebook' then clicks end as clicks,
       round((extract(epoch from captured_at - posted_at) / 3600)::numeric, 1) as post_age_hours, via
from u order by post_id, date_trunc('minute', captured_at), via desc
