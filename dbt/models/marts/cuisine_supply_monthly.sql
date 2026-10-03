-- Food POIs on the map per district x cuisine x month since 2010 (OSM history): supply growth per area.
select district, cuisine_tag, month, poi_count,
       poi_count - lag(poi_count, 12) over (partition by district, cuisine_tag order by month) as yoy_change
from {{ ref('stg_osm_history__monthly') }}
