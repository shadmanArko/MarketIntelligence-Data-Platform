{{ config(materialized='table', indexes=[{'columns': ['offering_id']}, {'columns': ['listing_id']}]) }}
-- Every menu item seen on any delivery platform, per menu observation.
with u as (
  select 'wolt' as platform, platform_id, offering_platform_id, observation_id, run_id, fetched_at as observed_at,
         category, name, description, price, original_price, null::numeric(10,2) as price_max, deposit, currency,
         dietary_tags, null::jsonb as size_variants, option_group_count, alcohol_permille, image_url, unavailable,
         position
  from {{ ref('stg_wolt__menu_item') }}
  union all
  select 'lieferando', platform_id, offering_platform_id, observation_id, run_id, fetched_at,
         category, name, description, price, null, price_max, null, currency,
         dietary_tags, size_variants, null, null, image_url, null, position
  from {{ ref('stg_lieferando__menu_item') }}
)
select
  md5(platform || ':' || platform_id || ':' || offering_platform_id)::uuid as offering_id,
  md5(platform || ':' || platform_id)::uuid                as listing_id,
  u.*,
  {{ fold('name') }}                                       as name_folded
from u
where name is not null
