-- Restaurant x postcode x observation: offered there, fee bands, ETA, rank, deals.
with src as {{ raw_entity('lieferando', 'coverage') }},
r as (
  select s.observation_id, s.run_id, s.fetched_at, s.natural_key as postcode, s.payload as p,
         e.value as v, e.ordinality as list_position
  from src s, jsonb_array_elements(ops.jarr(s.payload -> 'restaurants')) with ordinality e
)
select
  observation_id, run_id, fetched_at, postcode,
  (p #>> '{metaData,location,coordinates,1}')::float8      as point_lat,
  (p #>> '{metaData,location,coordinates,0}')::float8      as point_lon,
  v ->> 'id'                                               as platform_id,
  list_position::integer                                   as list_position,
  (v ->> 'defaultDisplayRank')::integer                    as display_rank,
  (select array_position(array(select jsonb_array_elements_text(ops.jarr(p #> '{promotedPlacement,rankedIds}'))), v ->> 'id'))
                                                           as promoted_rank,
  (v ->> 'isOpenNowForDelivery')::boolean                  as open_now_delivery,
  (v ->> 'isOpenNowForCollection')::boolean                as open_now_collection,
  (v ->> 'isTemporarilyOffline')::boolean                  as temporarily_offline,
  (v ->> 'deliveryCost')::numeric(10,2)                    as delivery_fee,
  (v ->> 'minimumDeliveryValue')::numeric(10,2)            as order_minimum,
  (v #>> '{deliveryEtaMinutes,rangeLower}')::integer       as eta_min_lower,
  (v #>> '{deliveryEtaMinutes,rangeUpper}')::integer       as eta_min_upper,
  (v ->> 'driveDistanceMeters')::integer                   as distance_m,
  (v ->> 'isPremier')::boolean                             as is_premier,
  (v ->> 'isTemporaryBoost')::boolean                      as is_temporary_boost,
  ops.jarr(v -> 'deals')                      as deals,
  p #> array['deliveryFees', 'restaurants', v ->> 'id', 'bands'] as fee_bands
from r
