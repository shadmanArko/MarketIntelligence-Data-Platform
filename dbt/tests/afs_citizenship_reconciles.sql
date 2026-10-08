-- AfS T10: per release, the non-aggregate rows add up exactly (no tolerance) to the grand total "Insgesamt" and to
-- every continent subtotal "<continent> zusammen", for residents, female and each age group. A release without
-- exactly one "Insgesamt" row fails too.
with c as (select * from {{ ref('stg_afs__citizenship') }}),
leaf as (
  select reference_date, continent, residents, female, age_under_15, age_15_45, age_45_65, age_65_plus
  from c where not is_aggregate
),
tot as (
  select reference_date, citizenship, count(*) over (partition by reference_date) as n_totals,
         residents, female, age_under_15, age_15_45, age_45_65, age_65_plus
  from c where citizenship = 'Insgesamt'
),
cont as (
  select reference_date, citizenship, continent, residents, female, age_under_15, age_15_45, age_45_65, age_65_plus
  from c where is_aggregate and region is null and citizenship <> 'Insgesamt'
),
chk as (
  select t.reference_date, t.citizenship, t.n_totals,
         array[t.residents, t.female, t.age_under_15, t.age_15_45, t.age_45_65, t.age_65_plus] as published,
         (select array[sum(residents), sum(female), sum(age_under_15), sum(age_15_45), sum(age_45_65), sum(age_65_plus)]
          from leaf l where l.reference_date = t.reference_date)::int[] as summed
  from tot t
  union all
  select a.reference_date, a.citizenship, 1,
         array[a.residents, a.female, a.age_under_15, a.age_15_45, a.age_45_65, a.age_65_plus],
         (select array[sum(residents), sum(female), sum(age_under_15), sum(age_15_45), sum(age_45_65), sum(age_65_plus)]
          from leaf l where l.reference_date = a.reference_date and l.continent = a.continent)::int[]
  from cont a
)
select * from chk where n_totals <> 1 or published is distinct from summed
union all
select r.reference_date, 'Insgesamt missing', 0, null, null
from (select distinct reference_date from c) r
where not exists (select 1 from tot t where t.reference_date = r.reference_date)
