-- Every version of every food POI (centroid, tags, valid from / to) per district (OSM history via ohsome).
with latest as (
  select distinct on (natural_key) natural_key as district, fetched_at, payload
  from {{ raw_entity('osm_history', 'element_history') }} s order by natural_key, fetched_at desc
)
select l.district,
       f.value #>> '{properties,@osmId}'                    as osm_id,
       (f.value #>> '{properties,@validFrom}')::timestamptz as valid_from,
       (f.value #>> '{properties,@validTo}')::timestamptz   as valid_to,
       (f.value #>> '{properties,@version}')::integer      as osm_version,
       f.value #>> '{properties,name}'                      as name,
       coalesce(f.value #>> '{properties,amenity}', f.value #>> '{properties,shop}') as poi_type,
       f.value #>> '{properties,cuisine}'                   as cuisine,
       (f.value #>> '{geometry,coordinates,1}')::float8     as lat,
       (f.value #>> '{geometry,coordinates,0}')::float8     as lon,
       f.value -> 'properties'                              as properties
from latest l, jsonb_array_elements(ops.jarr(l.payload -> 'features')) f
