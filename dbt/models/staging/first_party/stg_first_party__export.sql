-- Tenant posts + one metrics capture per post from delivered XLSX exports (Berlin local times -> UTC).
select 'dhaka-kacchi' as tenant_id, platform, external_id,
       (posted_berlin at time zone '{{ var("local_tz") }}') as posted_at, content_type,
       {{ clean_text("caption") }} as caption, permalink,
       (captured_berlin at time zone '{{ var("local_tz") }}') as captured_at,
       impressions, reach, likes, comments, shares, saves, clicks, file as source_file
from {{ dataset_table('first_party_social_export') }}
