{{ config(indexes=[{'columns': ['osm_id']}]) }}
-- One row per OSM food POI: first / last time on the map, name and cuisine changes, current presence.
select osm_id, max(district) as district,
       min(valid_from) as first_seen_on_map, max(valid_to) as last_seen_on_map,
       max(valid_to) >= date '2026-06-30' as on_map_at_extract_end,
       count(*) as versions, count(distinct name) as distinct_names, count(distinct cuisine) as distinct_cuisines,
       (array_agg(name order by valid_from desc))[1] as latest_name,
       (array_agg(cuisine order by valid_from desc))[1] as latest_cuisine,
       (array_agg(poi_type order by valid_from desc))[1] as latest_type,
       (array_agg(lat order by valid_from desc))[1] as lat, (array_agg(lon order by valid_from desc))[1] as lon
from {{ ref('stg_osm_history__element') }} group by 1
