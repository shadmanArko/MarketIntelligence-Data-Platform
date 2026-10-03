{{ config(post_hook=[
  "alter table {{ this }} enable row level security",
  "drop policy if exists tenant_isolation on {{ this }}",
  "create policy tenant_isolation on {{ this }} using (tenant_id = current_setting('app.tenant_id', true))"]) }}
-- Own post x capture time: reach, likes, comments, shares, saves, clicks, and post age at capture.
select md5(p.tenant_id || ':' || p.platform || ':' || p.external_id)::uuid as post_id, p.tenant_id, p.platform,
       (s.value ->> 'captured_at')::timestamptz as captured_at,
       (s.value ->> 'reach')::bigint as reach, (s.value ->> 'impressions')::bigint as impressions,
       (s.value ->> 'likes')::bigint as likes, (s.value ->> 'comments')::bigint as comments,
       (s.value ->> 'shares')::bigint as shares, (s.value ->> 'saves')::bigint as saves,
       (s.value ->> 'clicks')::bigint as clicks,
       round((extract(epoch from (s.value ->> 'captured_at')::timestamptz - p.posted_at) / 3600)::numeric, 1) as post_age_hours
from {{ ref('stg_first_party__own_post') }} p, jsonb_array_elements(ops.jarr(p.snapshots)) s
