{{ config(indexes=[{'columns': ['day']}, {'columns': ['community_id', 'occasion_type']}]) }}
-- Day x community x occasion, 2015-2030, with meaning (food role, tone, lead time) and the greeting to use.
-- Islamic dates are estimates (±1 day; moon_offset applied per community for rule-based ones).
with cal as (
  select day, community_id, occasion_type,
         array_agg(distinct holiday_name) as holiday_names,
         array_agg(distinct holiday_name_native) filter (where holiday_name_native is not null) as holiday_names_native,
         array_agg(distinct country) filter (where country is not null) as countries,
         bool_or(is_estimated) as is_estimated, min(source) as source, max(calendar_version) as calendar_version
  from {{ ref('stg_occasions__calendar') }}
  where occasion_type <> 'other'
  group by 1, 2, 3
),
greet as (   -- the community's greeting for this occasion; Eid greetings also cover Ramadan-adjacent days
  select community_id, greeting_key, text, translit, needs_review from {{ ref('community_greeting') }}
)
select cal.*, ot.food_role, ot.tone, ot.lead_days, (cal.day - ot.lead_days) as content_window_start,
       g.text as greeting, g.translit as greeting_translit, g.needs_review as greeting_needs_review,
       s.sunset as iftar_at, s.dawn_18 as suhoor_ends_at
from cal
left join {{ ref('occasion_type') }} ot using (occasion_type)
left join greet g on g.community_id = cal.community_id and g.greeting_key = case
     when cal.occasion_type in ('ramadan_period', 'iftar_season_peak', 'laylat_al_qadr') then 'ramadan'
     when cal.occasion_type = 'orthodox_christmas' and exists (select 1 from greet x where x.community_id = cal.community_id
          and x.greeting_key = 'orthodox_christmas') then 'orthodox_christmas'
     when cal.occasion_type = 'orthodox_christmas' then 'christmas'
     when cal.occasion_type = 'dashain' then 'dashain'
     else cal.occasion_type end
left join {{ dataset_table('sun_times_berlin') }} s on s.day = cal.day
  and cal.occasion_type in ('ramadan_period', 'iftar_season_peak', 'laylat_al_qadr', 'ramadan')
