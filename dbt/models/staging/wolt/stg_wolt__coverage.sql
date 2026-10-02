-- Listing x grid cell x observation: is the venue offered at this point, and at what fee / estimate.
with src as {{ raw_entity('wolt', 'coverage') }},
v as (
  select s.observation_id, s.run_id, s.fetched_at, s.natural_key as cell,
         (s.payload ->> 'lat')::float8 as point_lat, (s.payload ->> 'lon')::float8 as point_lon,
         e.value as v, e.ordinality as list_position
  from src s, jsonb_array_elements(ops.jarr(s.payload -> 'venues')) with ordinality e
)
select
  observation_id, run_id, fetched_at, cell, point_lat, point_lon,
  v ->> 'venue_id'                                         as platform_id,
  v ->> 'section'                                          as section,
  list_position::integer                                   as list_position,
  (v #>> '{venue,delivers}')::boolean                      as delivers,
  (v #>> '{venue,online}')::boolean                        as online,
  (v #>> '{venue,estimate}')::integer                      as delivery_estimate_min,
  v #>> '{venue,estimate_range}'                           as delivery_estimate_range,
  -- sortables are rank positions for sorting, not amounts
  (select (x ->> 'value')::integer from jsonb_array_elements(ops.jarr(v #> '{sorting,sortables}')) x
     where x ->> 'id' = 'delivery-price')                  as delivery_price_rank,
  (select (x ->> 'value')::integer from jsonb_array_elements(ops.jarr(v #> '{sorting,sortables}')) x
     where x ->> 'id' = 'rating')                          as rating_rank,
  (select (x ->> 'value')::integer from jsonb_array_elements(ops.jarr(v #> '{sorting,sortables}')) x
     where x ->> 'id' = 'distance')                        as distance_rank,
  (select (x ->> 'value')::integer from jsonb_array_elements(ops.jarr(v #> '{sorting,sortables}')) x
     where x ->> 'id' = 'preparation-estimate')            as preparation_rank,
  ops.jarr(v #> '{venue,promotions}')         as promotions,
  ops.jarr(coalesce(v #> '{venue,badges_v2}', v #> '{venue,badges}')) as badges,
  (v #>> '{venue,show_wolt_plus}')::boolean                as wolt_plus
from v
