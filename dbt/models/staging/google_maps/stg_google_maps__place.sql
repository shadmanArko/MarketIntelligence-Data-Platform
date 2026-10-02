-- Google Maps place entries (positional arrays from the Maps web search). Index map documented in
-- src/mip/connectors/google_maps.py; every value stays available in `entry`.
with src as {{ raw_entity('google_maps', 'place') }}
select
  observation_id, run_id, fetched_at, payload_sha256,
  natural_key                                              as platform_id,      -- Maps feature id 0x..:0x..
  e #>> '{78}'                                             as google_place_id,  -- ChIJ...
  e #>> '{89}'                                             as kg_mid,
  {{ clean_text("e #>> '{11}'") }}                         as name,
  {{ clean_text("e #>> '{39}'") }}                         as address_full,
  {{ clean_text("e #>> '{2,0}'") }}                        as address_line,
  {{ postcode("e #>> '{2,1}'") }}                          as postcode,
  nullif(e #>> '{166}', '')                                as city,
  nullif(e #>> '{14}', '')                                 as neighbourhood,
  (e #>> '{9,2}')::float8                                  as lat,
  (e #>> '{9,3}')::float8                                  as lon,
  (e #>> '{4,7}')::numeric(3,2)                            as rating_value,     -- 1-5
  (e #>> '{4,8}')::integer                                 as rating_count,     -- NULL when the search omitted it
  nullif(e #>> '{4,2}', '')                                as price_band,
  ops.jarr(e -> 13)                           as categories,
  nullif(e #>> '{13,0}', '')                               as primary_category,
  {{ clean_url("e #>> '{7,0}'") }}                         as website,
  e #>> '{178,0,0}'                                        as phone_raw,
  {{ phone_e164("e #>> '{178,0,3}'") }}                    as phone,
  {{ clean_text("e #>> '{32,0,1}'") }}                     as short_description,
  {{ clean_text("e #>> '{32,1,1}'") }}                     as description,
  {{ clean_text("e #>> '{57,1}'") }}                       as owner_name,
  e #>> '{57,2}'                                           as owner_account_id,
  e #>> '{30}'                                             as timezone,
  e -> 203                                                 as opening_hours,
  e -> 100                                                 as attributes_raw,
  ops.jarr(e -> 46)                           as order_links,
  e #>> '{88,1}'                                           as result_type,
  e #>> '{157}'                                            as image_url,
  case when payload::text ~ 'Dauerhaft geschlossen|Permanently closed' then 'closed_permanently'
       when payload::text ~ 'Vorübergehend geschlossen|Temporarily closed' then 'closed_temporarily'
       else 'operational' end                              as business_status,
  e                                                        as entry
from src, lateral (select payload -> 'entry' as e) x
