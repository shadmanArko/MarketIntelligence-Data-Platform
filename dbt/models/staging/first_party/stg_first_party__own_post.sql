-- Tenant's own posts (Instagram / Facebook / Threads) from the AI Harness warehouse, latest copy of each.
select distinct on (natural_key)
  payload ->> 'tenant_id' as tenant_id, payload ->> 'platform' as platform, payload ->> 'external_id' as external_id,
  (payload ->> 'posted_at')::timestamptz as posted_at, payload ->> 'content_type' as content_type,
  {{ clean_text("payload ->> 'caption'") }} as caption, payload ->> 'permalink' as permalink,
  payload -> 'snapshots' as snapshots, fetched_at as observed_at
from {{ raw_entity('first_party', 'own_post') }} s
order by natural_key, fetched_at desc
