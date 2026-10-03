-- Residents with migration background by origin area: per LOR planning area (A I 16, T4) and per district by
-- German-with-MH / foreigner (A I 5, T9). Origin labels -> codes used in communities.yaml (afs_origin).
with t as (
  select reference_date, sheet, section,
         case when sheet = 'T4' then key1 || key2 || key3 || key4 end as lor_code,
         case when sheet = 'T4' then key1 else left(key1, 2) end as district_code,
         regexp_replace(regexp_replace(column_label, '^(Darunter aus Herkunftsgebiet / )?(darunter / )?', ''), '-', '', 'g')
           as origin_label,
         value
  from {{ dataset_table('afs_population') }}
  where sheet in ('T4', 'T9') and key1 ~ '^\d{2}'
)
select reference_date, case when sheet = 'T4' then 'lor' else 'district' end as level, lor_code, district_code,
  case when sheet = 'T9' then split_part(section, ' / ', 1) else 'insgesamt' end as person_group,
  case when sheet = 'T9' then split_part(section, ' / ', 2) else 'insgesamt' end as sex,
  origin_label,
  case origin_label
    when 'Insgesamt' then 'ALL' when 'Europäische Union (EU) 1' then 'EU' when 'Frankreich' then 'FR'
    when 'Griechenland' then 'GR' when 'Italien' then 'IT' when 'Österreich' then 'AT' when 'Spanien' then 'ES'
    when 'Polen' then 'PL' when 'Bulgarien' then 'BG' when 'Rumänien' then 'RO' when 'Kroatien' then 'HR'
    when 'Vereinigtes Königreich' then 'UK' when 'Russische Föderation' then 'RU' when 'Ukraine' then 'UA'
    when 'Kasachstan' then 'KZ' when 'Türkei' then 'TR' when 'Afghanistan' then 'AF' when 'Iran' then 'IR'
    when 'Libanon' then 'LB' when 'Syrien' then 'SY' when 'Irak' then 'IQ' when 'China' then 'CN'
    when 'Indien' then 'IN' when 'Vietnam' then 'VN' when 'Vereinigte Staaten/ USA' then 'US'
    else 'OTHER' end as origin_code,
  value::int as residents
from t
