-- One row per Lieferando restaurant observation from the postcode sweep (stable attributes).
with src as {{ raw_entity('lieferando', 'restaurant_listing') }}
select
  observation_id, run_id, fetched_at, payload_sha256,
  natural_key                                              as platform_id,
  {{ clean_text("payload ->> 'name'") }}                   as name,
  payload ->> 'uniqueName'                                 as slug,
  {{ clean_text("payload #>> '{address,firstLine}'") }}    as address_line,
  payload #>> '{address,postalCode}'                       as postcode,
  payload #>> '{address,city}'                             as city,
  (payload #>> '{address,location,coordinates,1}')::float8 as lat,
  (payload #>> '{address,location,coordinates,0}')::float8 as lon,
  (payload #>> '{rating,starRating}')::numeric(4,2)        as rating_value,       -- 0-5
  (payload #>> '{rating,count}')::integer                  as rating_count,
  (payload ->> 'isNew')::boolean                           as is_new,
  (payload ->> 'isDelivery')::boolean                      as offers_delivery,
  (payload ->> 'isCollection')::boolean                    as offers_collection,
  (payload ->> 'isTestRestaurant')::boolean                as is_test,
  ops.jarr(payload -> 'cuisines')             as cuisines,
  ops.jarr(payload -> 'tags')                 as tags,
  payload ->> 'logoUrl'                                    as logo_url,
  payload                                                  as attributes
from src
