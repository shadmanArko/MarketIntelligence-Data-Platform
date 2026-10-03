{{ config(post_hook=[
  "alter table {{ this }} enable row level security",
  "drop policy if exists tenant_isolation on {{ this }}",
  "create policy tenant_isolation on {{ this }} using (tenant_id = current_setting('app.tenant_id', true))"]) }}
-- The tenant's own posts (row-level security: a tenant role only sees rows with its tenant_id).
select md5(tenant_id || ':' || platform || ':' || external_id)::uuid as post_id, tenant_id, platform, external_id,
       posted_at, content_type, caption, permalink, length(caption) as caption_length,
       array(select lower(m[1]) from regexp_matches(coalesce(caption, ''), '#([[:alnum:]_äöüß]+)', 'g') m) as hashtags,
       extract(isodow from posted_at at time zone '{{ var("local_tz") }}') as posted_weekday_berlin,
       extract(hour from posted_at at time zone '{{ var("local_tz") }}') as posted_hour_berlin
from {{ ref('stg_first_party__own_post') }}
