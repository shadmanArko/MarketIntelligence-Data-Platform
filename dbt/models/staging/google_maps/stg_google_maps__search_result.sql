-- Which place ranked where for which query in which cell (search visibility per area).
with src as {{ raw_entity('google_maps', 'search_page') }}
select
  s.observation_id, s.run_id, s.fetched_at,
  s.payload ->> 'query'                                    as query,
  s.payload ->> 'cell'                                     as cell,
  (s.payload ->> 'lat')::float8                            as point_lat,
  (s.payload ->> 'lon')::float8                            as point_lon,
  (s.payload ->> 'viewport_m')::integer                    as viewport_m,
  r.value ->> 'fid'                                        as platform_id,
  (r.value ->> 'rank')::integer                            as rank
from src s, jsonb_array_elements(ops.jarr(s.payload -> 'results')) r
