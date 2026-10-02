{{ config(materialized='table', indexes=[{'columns': ['business_id'], 'unique': True}, {'columns': ['geog'], 'type': 'gist'}]) }}
-- Geography columns for core.business (kept separate so business.sql stays readable).
select business_id, {{ geog('lat', 'lon') }} as geog, {{ h3_r8('lat', 'lon') }} as h3_r8,
       case when lat is not null then h3_lat_lng_to_cell(point(lon, lat), 9)::text end as h3_r9,
       case when lat is not null then h3_lat_lng_to_cell(point(lon, lat), 7)::text end as h3_r7
from {{ ref('business') }}
