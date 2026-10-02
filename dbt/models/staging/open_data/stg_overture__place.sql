-- Food-related Overture places (latest registered release), every column kept.
select
  id                                                       as platform_id,
  {{ dataset_version('overture_places') }}                 as dataset_version,
  {{ clean_text("names::jsonb ->> 'primary'") }}           as name,
  lat, lon,
  basic_category,
  taxonomy::jsonb ->> 'primary'                            as category_primary,
  taxonomy::jsonb -> 'hierarchy'                           as category_hierarchy,
  taxonomy::jsonb -> 'alternates'                          as category_alternates,
  confidence::numeric(5,4)                                 as confidence,
  operating_status,
  {{ clean_text("addresses::jsonb #>> '{0,freeform}'") }}  as address_line,
  addresses::jsonb #>> '{0,postcode}'                      as postcode,
  addresses::jsonb #>> '{0,locality}'                      as city,
  {{ clean_url("websites::jsonb ->> 0") }}                 as website,
  {{ phone_e164("phones::jsonb ->> 0") }}                  as phone,
  socials::jsonb                                           as socials,
  brand::jsonb #>> '{names,primary}'                       as brand,
  brand::jsonb ->> 'wikidata'                              as brand_wikidata,
  sources::jsonb                                           as sources
from {{ dataset_table('overture_places') }}
where taxonomy::jsonb #>> '{hierarchy,0}' = 'food_and_drink'
   or basic_category in ('restaurant','casual_eatery','cafe','coffee_shop','bar','fast_food_restaurant','food_service')
   or taxonomy::jsonb -> 'hierarchy' ?| array['bakery','patisserie','confectionery','dessert_shop','ice_cream_shop']
