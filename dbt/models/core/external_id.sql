{{ config(materialized='table', indexes=[{'columns': ['business_id']}, {'columns': ['source', 'external_id']}]) }}
-- Every outside identifier of a business, so each new dataset release links with one join.
select a.business_id, l.platform as source, l.platform_id as external_id, l.listing_key, a.match_prob, a.method
from ops.business_assignment a join {{ ref('listing') }} l using (listing_key)
union all
select a.business_id, 'google_place_id', g.google_place_id, l.listing_key, a.match_prob, a.method
from ops.business_assignment a join {{ ref('listing') }} l using (listing_key)
join (select distinct on (platform_id) platform_id, google_place_id from {{ ref('stg_google_maps__place') }}
      where google_place_id is not null order by platform_id, fetched_at desc) g on g.platform_id = l.platform_id
where l.platform = 'google_maps'
