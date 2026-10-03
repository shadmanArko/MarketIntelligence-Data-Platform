-- The content calendar: every community occasion from a week ago to 15 months ahead, with when to start posting,
-- the greeting in the community's language, the community's own meat-and-rice dishes to bridge to biryani, how many
-- of them live in Berlin and where, iftar / suhoor times in Ramadan, and Berlin events on the same day.
with latest as (select max(reference_date) as d from {{ ref('community_audience') }}),
size as (
  select a.community_id,
         max(a.residents) filter (where a.level = 'berlin_citizens') as berlin_citizens,
         (select array_agg(x.area_code || ':' || x.residents order by x.residents desc)
            from (select area_code, residents from {{ ref('community_audience') }} b, latest
                  where b.community_id = a.community_id and b.level = 'district_mh' and b.reference_date = latest.d
                  order by residents desc limit 3) x) as top_districts_mh
  from {{ ref('community_audience') }} a, latest where a.reference_date = latest.d
  group by a.community_id
),
dishes as (
  select community_id, array_agg(english || ' — ' || native_name order by dish_id) as bridge_dishes
  from {{ ref('community_dish') }} group by 1
),
events as (
  select d::date as day, array_agg(distinct name) as berlin_events
  from (select distinct on (event_id, feed) * from {{ ref('stg_berlin_events__event') }}
        order by event_id, feed, fetched_at desc) e,
       generate_series(starts_on, ends_on, interval '1 day') d
  group by 1
)
select o.day, extract(isodow from o.day)::int as iso_weekday, o.community_id, coalesce(c.label, 'All Berlin') as community,
       o.occasion_type, o.holiday_names, o.holiday_names_native, o.countries, o.food_role, o.tone,
       o.content_window_start, o.is_estimated,
       o.greeting, o.greeting_translit, o.greeting_needs_review,
       d.bridge_dishes, s.berlin_citizens, s.top_districts_mh,
       to_char(o.iftar_at at time zone '{{ var("local_tz") }}', 'HH24:MI') as iftar_local,
       to_char(o.suhoor_ends_at at time zone '{{ var("local_tz") }}', 'HH24:MI') as suhoor_ends_local,
       e.berlin_events
from {{ ref('occasion_day') }} o
left join {{ ref('community') }} c using (community_id)
left join dishes d using (community_id)
left join size s using (community_id)
left join events e using (day)
where o.day between current_date - 7 and current_date + 460
  and o.occasion_type not in ('payday')
