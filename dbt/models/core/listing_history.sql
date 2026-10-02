{{ config(materialized='table', indexes=[{'columns': ['listing_id', 'valid_from']}]) }}
-- SCD Type 2 over the stable attributes of each listing: a new row whenever name, address, contact,
-- legal entity, brand or price range change between consecutive observations.
with obs as (
  select listing_id, listing_key, platform, observed_at, name, address_line, postcode, phone, website, legal_name,
         legal_register_id, vat_number, brand_name, price_range,
         {{ attr_hash(['name', 'address_line', 'postcode', 'phone', 'website', 'legal_name', 'legal_register_id',
                       'vat_number', 'brand_name', 'price_range']) }} as h
  from {{ ref('int_listing_observation') }}
  where obs_kind in ('venue_static', 'menu_manifest', 'place', 'poi', 'restaurant_listing', 'venue_listing')
    and name is not null
),
marked as (
  select *, case when h is distinct from lag(h) over w then 1 else 0 end as changed
  from obs window w as (partition by listing_id order by observed_at)
),
grp as (select *, sum(changed) over (partition by listing_id order by observed_at) as version from marked),
versions as (
  select listing_id, listing_key, platform, version, min(observed_at) as valid_from,
         (array_agg(name order by observed_at))[1] as name,
         (array_agg(address_line order by observed_at))[1] as address_line,
         (array_agg(postcode order by observed_at))[1] as postcode,
         (array_agg(phone order by observed_at))[1] as phone,
         (array_agg(website order by observed_at))[1] as website,
         (array_agg(legal_name order by observed_at))[1] as legal_name,
         (array_agg(legal_register_id order by observed_at))[1] as legal_register_id,
         (array_agg(vat_number order by observed_at))[1] as vat_number,
         (array_agg(brand_name order by observed_at))[1] as brand_name,
         (array_agg(price_range order by observed_at))[1] as price_range,
         count(*) as observations
  from grp group by 1, 2, 3, 4
)
select *, lead(valid_from) over (partition by listing_id order by valid_from) as valid_to,
       lead(valid_from) over (partition by listing_id order by valid_from) is null as is_current
from versions
