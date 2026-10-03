-- Uber Eats stores (one-time Apify store list). Field names vary slightly by actor version: coalesce them.
with src as {{ raw_entity('uber_eats', 'store') }}
select
  observation_id, run_id, fetched_at, payload_sha256,
  natural_key                                              as platform_id,
  {{ clean_text("payload ->> 'title'") }}                  as name,
  payload ->> 'url'                                        as share_url,
  {{ clean_text("coalesce(payload ->> 'formattedAddress', payload #>> '{location,address}', payload ->> 'address')") }} as address_full,
  {{ clean_text("split_part(coalesce(payload ->> 'formattedAddress', payload ->> 'address'), ',', 1)") }} as address_line,
  {{ postcode("coalesce(payload ->> 'formattedAddress', payload ->> 'address')") }} as postcode,
  coalesce(payload ->> 'latitude', payload #>> '{location,latitude}', payload ->> 'lat')::float8   as lat,
  coalesce(payload ->> 'longitude', payload #>> '{location,longitude}', payload ->> 'lng', payload ->> 'lon')::float8 as lon,
  nullif(regexp_replace(coalesce(payload ->> 'ratingValue', payload #>> '{rating,ratingValue}', ''), '[^0-9.]', '', 'g'), '')::numeric(3,2) as rating_value,  -- 1-5
  nullif(regexp_replace(coalesce(payload ->> 'ratingCount', payload ->> 'reviewCount', payload #>> '{rating,reviewCount}', ''), '[^0-9]', '', 'g'), '')::integer as rating_count,
  length(nullif(regexp_replace(coalesce(payload ->> 'priceBucket', ''), '[^$€£]', '', 'g'), ''))::smallint as price_range,
  payload ->> 'etaText'                                    as eta_text,
  ops.jarr(coalesce(payload -> 'cuisineSlugs', payload -> 'cuisines', payload -> 'categories', payload -> 'tags')) as cuisines,
  payload                                                  as attributes
from src
