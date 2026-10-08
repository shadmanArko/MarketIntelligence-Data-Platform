-- How many people of each community live in Berlin and where (Amt für Statistik Berlin-Brandenburg).
--   level = berlin_citizens  foreign citizens of the community's countries, Berlin total (T10; every country)
--           district_mh      residents with migration background from the community's origin areas, per district
--           lor_mh           the same per LOR planning area (only 24 origin areas are published below city level)
-- share = residents / all residents with migration background in that area (district / LOR levels).
with com as (
  select community_id, string_to_array(nullif(afs_citizenship, ''), '|') as cits,
         string_to_array(nullif(afs_origin, ''), '|') as origins
  from {{ ref('community') }}
),
cit as (
  select c.reference_date, com.community_id, 'berlin_citizens' as level, '11' as area_code,
         sum(c.residents) as residents, null::float8 as share
  from {{ ref('stg_afs__citizenship') }} c join com on c.citizenship = any(com.cits)
  where not c.is_aggregate                  -- subtotals ("Insgesamt", "Asien zusammen") never count as a community
  group by 1, 2
),
o as (
  select * from {{ ref('stg_afs__origin_area') }}
  where person_group = 'insgesamt' and sex = 'insgesamt'
),
tot as (
  select reference_date, level, coalesce(lor_code, district_code) as area_code, residents as total_mh
  from o where origin_code = 'ALL'
),
mh as (
  select o.reference_date, com.community_id, case o.level when 'lor' then 'lor_mh' else 'district_mh' end as level,
         coalesce(o.lor_code, o.district_code) as area_code, sum(o.residents) as residents
  from o join com on o.origin_code = any(com.origins)
  group by 1, 2, 3, 4
)
select reference_date, community_id, level, area_code, residents::int, share from cit
union all
select mh.reference_date, mh.community_id, mh.level, mh.area_code, mh.residents::int,
       mh.residents::float8 / nullif(t.total_mh, 0)
from mh join tot t on t.reference_date = mh.reference_date and t.area_code = mh.area_code
  and t.level = case mh.level when 'lor_mh' then 'lor' else 'district' end
