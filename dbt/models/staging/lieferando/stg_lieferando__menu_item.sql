-- One row per menu item variation (size variants are separate prices of one offering).
with src as {{ raw_entity('lieferando', 'menu_items') }},
man as (
  select distinct on (natural_key) natural_key as slug, payload -> 'Menus' as menus
  from {{ raw_entity('lieferando', 'menu_manifest') }} m
  order by natural_key, fetched_at desc
),
cat as (
  select distinct on (m.slug, iid.value #>> '{}') m.slug, c.value ->> 'Name' as category, iid.value #>> '{}' as item_id
  from man m, jsonb_array_elements(ops.jarr(m.menus)) mm, jsonb_array_elements(ops.jarr(mm.value -> 'Categories')) with ordinality c,
       jsonb_array_elements(ops.jarr(c.value -> 'ItemIds')) iid
  order by m.slug, iid.value #>> '{}', c.ordinality
),
items as (
  select s.observation_id, s.run_id, s.fetched_at, s.request_meta ->> 'restaurant_id' as platform_id,
         s.natural_key as slug, i.value as it, i.ordinality as position
  from src s, jsonb_array_elements(ops.jarr(s.payload -> 'Items')) with ordinality i
)
select
  i.observation_id, i.run_id, i.fetched_at, i.platform_id, i.slug,
  i.it ->> 'Id'                                            as offering_platform_id,
  cat.category,
  {{ clean_text("i.it ->> 'Name'") }}                      as name,
  {{ clean_text("i.it ->> 'Description'") }}               as description,
  (select min((v.value ->> 'BasePrice')::numeric) from jsonb_array_elements(ops.jarr(i.it -> 'Variations')) v)::numeric(10,2) as price,
  (select max((v.value ->> 'BasePrice')::numeric) from jsonb_array_elements(ops.jarr(i.it -> 'Variations')) v)::numeric(10,2) as price_max,
  'EUR'                                                    as currency,
  jsonb_array_length(ops.jarr(i.it -> 'Variations')) as variant_count,
  (select jsonb_agg(jsonb_build_object('name', v.value ->> 'Name', 'price', (v.value ->> 'BasePrice')::numeric,
                                       'deal_only', (v.value ->> 'DealOnly')::boolean))
     from jsonb_array_elements(ops.jarr(i.it -> 'Variations')) v)    as size_variants,
  ops.jarr(i.it -> 'Labels')                  as dietary_tags,
  i.it ->> 'Type'                                          as item_type,
  i.it #>> '{ImageSources,0,Path}'                         as image_url,
  i.position::integer                                      as position,
  i.it                                                     as attributes
from items i
left join cat on cat.slug = i.slug and cat.item_id = i.it ->> 'Id'
