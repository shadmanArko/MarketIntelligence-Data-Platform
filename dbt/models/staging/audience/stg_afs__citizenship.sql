-- Foreign residents of Berlin by citizenship (A I 5, T10): total, female and 4 age groups, per half-year release.
with c as (
  select reference_date, key2 as citizenship, split_part(section, ' / ', 2) as continent, column_label, value
  from {{ dataset_table('afs_population') }}
  where sheet = 'T10 G1' and key2 is not null
)
select reference_date, citizenship, nullif(continent, '') as continent,
  max(value) filter (where column_label = 'Insgesamt / insgesamt')::int as residents,
  max(value) filter (where column_label = 'Darunter weiblich / zusammen')::int as female,
  max(value) filter (where column_label like 'Insgesamt / % / unter 15')::int as age_under_15,
  max(value) filter (where column_label like 'Insgesamt / % / 15 - 45')::int as age_15_45,
  max(value) filter (where column_label like 'Insgesamt / % / 45 - 65')::int as age_45_65,
  max(value) filter (where column_label like 'Insgesamt / % / 65 und mehr')::int as age_65_plus
from c group by 1, 2, 3
