{{ config(materialized='table', indexes=[{'columns': ['offering_id'], 'unique': True}, {'columns': ['listing_id']},
                                          {'columns': ['dish_id']}]) }}
-- One offering (menu item) on one listing, current attributes + canonical dish + dietary flags.
with latest as (
  select distinct on (offering_id) *
  from {{ ref('int_offering_observation') }}
  order by offering_id, observed_at desc
),
span as (
  select offering_id, min(observed_at) as first_seen_at, max(observed_at) as last_seen_at, count(*) as observations
  from {{ ref('int_offering_observation') }} group by 1
),
dish as (
  select distinct on (l.offering_id) l.offering_id, d.dish_id, d.pattern as dish_pattern
  from latest l
  join {{ ref('dish_map') }} d
    on position(d.pattern in l.name_folded) > 0
   and l.name_folded ~ (case when length(d.pattern) <= 4 then '\m' || d.pattern || '\M' else '\m' || d.pattern end)
  order by l.offering_id, d.priority, length(d.pattern) desc
),
text_flags as (
  select offering_id, {{ fold("coalesce(name, '') || ' ' || coalesce(description, '') || ' ' || coalesce(category, '') || ' ' || coalesce(dietary_tags::text, '')") }} as t
  from latest
)
select
  l.offering_id, l.listing_id, l.platform, l.platform_id, l.offering_platform_id,
  l.category, l.name, l.description, l.name_folded, l.image_url, l.position,
  d.dish_id, d.dish_pattern,
  l.dietary_tags,
  jsonb_build_object(
    'halal',      tf.t ~ '\mhalal\M',
    'vegan',      tf.t ~ '\mvegan',
    'vegetarian', tf.t ~ '\m(vegetari|veggie)',
    'spicy',      tf.t ~ '\m(scharf|spicy|hot|chili|chilli)\M',
    'gluten_free',tf.t ~ '(glutenfrei|gluten free|gluten-free)',
    'contains_pork', tf.t ~ '\m(schwein|pork|bacon|speck|salami|schinken)',
    'alcohol',    coalesce(l.alcohol_permille, 0) > 0 or tf.t ~ '\m(bier|beer|wein|wine|vodka|whisky|rum|gin|sekt|prosecco)\M',
    'drink',      tf.t ~ '\m(getraenk|drinks?|cola|fanta|sprite|wasser|water|saft|juice|lassi|tee|tea|kaffee|coffee|ayran|borhani)'
  )                                                        as attributes,
  l.option_group_count, l.size_variants,
  coalesce(l.unavailable, false)                           as unavailable_at_last_seen,
  s.first_seen_at, s.last_seen_at, s.observations
from latest l
join span s using (offering_id)
join text_flags tf using (offering_id)
left join dish d using (offering_id)
