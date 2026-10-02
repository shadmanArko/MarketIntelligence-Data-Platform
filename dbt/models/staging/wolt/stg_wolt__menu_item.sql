-- One row per menu item per menu observation, with its category.
with src as {{ raw_entity('wolt', 'menu') }},
items as (
  select s.observation_id, s.run_id, s.fetched_at, s.request_meta ->> 'venue_id' as platform_id, s.natural_key as slug,
         i.value as it, i.ordinality as position
  from src s, jsonb_array_elements(ops.jarr(s.payload -> 'items')) with ordinality i
)
select
  i.observation_id, i.run_id, i.fetched_at, i.platform_id, i.slug,
  i.it ->> 'id'                                            as offering_platform_id,
  cat.category,
  cat.category_slug,
  {{ clean_text("i.it ->> 'name'") }}                      as name,
  {{ clean_text("i.it ->> 'description'") }}               as description,
  {{ cents("i.it ->> 'price'") }}                          as price,
  {{ cents("i.it ->> 'original_price'") }}                 as original_price,
  {{ cents("i.it #>> '{deposit,amount}'") }}               as deposit,
  'EUR'                                                    as currency,
  ops.jarr(i.it -> 'dietary_preferences')     as dietary_tags,
  (i.it ->> 'alcohol_permille')::integer                   as alcohol_permille,
  jsonb_array_length(ops.jarr(i.it -> 'options')) as option_group_count,
  i.it -> 'options'                                        as options,
  i.it #>> '{images,0,url}'                                as image_url,
  (i.it -> 'disabled_info') is not null and i.it -> 'disabled_info' <> 'null'::jsonb as unavailable,
  i.position::integer                                      as position,
  i.it                                                     as attributes
from items i
join src s on s.observation_id = i.observation_id
left join lateral (
  select c.value ->> 'name' as category, c.value ->> 'slug' as category_slug
  from jsonb_array_elements(ops.jarr(s.payload -> 'categories')) c
  where c.value -> 'item_ids' ? (i.it ->> 'id')
  order by (c.value ->> 'slug') in ('highlights', 'popular', 'beliebt') or c.value ->> 'slug' like 'highlights%'
  limit 1
) cat on true
