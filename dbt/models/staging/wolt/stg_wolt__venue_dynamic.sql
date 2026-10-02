-- Ordering conditions at the venue's own location: minimum order, delivery configs, discounts, surcharges.
with src as {{ raw_entity('wolt', 'venue_dynamic') }}
select
  observation_id, run_id, fetched_at,
  payload #>> '{venue,id}'                                 as platform_id,
  natural_key                                              as slug,
  {{ cents("payload ->> 'order_minimum'") }}               as order_minimum,
  (payload #>> '{venue,online}')::boolean                  as online,
  payload #>> '{venue,open_status,style,type}'             as open_status,
  (payload #>> '{venue_raw,preestimate_total,mean}')::integer       as delivery_estimate_min,
  (payload #>> '{venue_raw,preestimate_preparation,mean}')::integer as preparation_estimate_min,
  ops.jarr(payload #> '{venue_raw,discounts}') as discounts,
  jsonb_array_length(ops.jarr(payload #> '{venue_raw,discounts}')) as discount_count,
  ops.jarr(payload #> '{venue_raw,surcharges}') as surcharges,
  ops.jarr(payload #> '{venue,delivery_configs}') as delivery_configs,
  (payload #>> '{venue_raw,self_delivery}')::boolean       as self_delivery,
  payload #> '{venue_raw,delivery_specs,geo_range}'        as delivery_area_geojson,
  payload                                                  as attributes
from src
