-- One row per Wolt venue observation from the grid sweep (stable venue attributes).
with src as {{ raw_entity('wolt', 'venue_listing') }}
select
  observation_id, run_id, fetched_at, payload_sha256,
  natural_key                                              as platform_id,
  {{ clean_text("payload #>> '{venue,name}'") }}           as name,
  payload #>> '{venue,slug}'                               as slug,
  {{ clean_text("payload #>> '{venue,address}'") }}        as address_line,
  nullif(payload #>> '{venue,city}', '')                   as city,
  payload #>> '{venue,country}'                            as country,
  (payload #>> '{venue,location,1}')::float8               as lat,
  (payload #>> '{venue,location,0}')::float8               as lon,
  nullif(payload #>> '{venue,franchise}', '')              as franchise,
  payload #>> '{venue,product_line}'                       as product_line,
  (payload #>> '{venue,price_range}')::smallint            as price_range,
  payload #>> '{venue,currency}'                           as currency,
  (payload #>> '{venue,rating,score}')::numeric(4,2)       as rating_value,       -- Wolt scale 0-10
  (payload #>> '{venue,rating,volume}')::integer           as rating_count,
  (payload #>> '{venue,rating,rating}')::smallint          as rating_bucket,
  {{ clean_text("payload #>> '{venue,short_description}'") }} as short_description,
  ops.jarr(payload #> '{venue,tags}')         as tags,
  ops.jarr(payload #> '{venue,categories}')   as categories,
  payload #>> '{image,url}'                                as cover_image_url,
  payload #>> '{venue,brand_image,url}'                    as logo_url,
  ops.jarr(payload #> '{venue,venue_preview_items}') as preview_items,
  payload                                                  as attributes
from src
