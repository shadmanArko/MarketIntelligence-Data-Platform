-- Monthly count of food POIs per Berlin district x cuisine tag (OSM history via ohsome).
with latest as (
  select distinct on (natural_key) natural_key as district, fetched_at, payload
  from {{ raw_entity('osm_history', 'monthly_counts') }} s order by natural_key, fetched_at desc
)
select l.district, replace(g.value ->> 'groupByObject', 'cuisine=', '') as cuisine_tag,
       (r.value ->> 'timestamp')::timestamptz::date as month, (r.value ->> 'value')::float8::integer as poi_count
from latest l, jsonb_array_elements(ops.jarr(l.payload -> 'groupByResult')) g,
     jsonb_array_elements(ops.jarr(g.value -> 'result')) r
