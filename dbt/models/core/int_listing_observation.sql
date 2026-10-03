{{ config(materialized='table', indexes=[{'columns': ['listing_key']}, {'columns': ['observed_at']}]) }}
-- Every observation of a place on any platform, in one shape. NULL = not provided by that observation.
-- core.listing (current state), core.listing_history (SCD2) and core.listing_snapshot are built from this.

with unioned as (
  -- wolt_list
  select 'wolt' as platform, platform_id, 'venue_listing' as obs_kind, observation_id, run_id, fetched_at as observed_at,
         name, address_line, null::text as postcode, city, lat, lon, null::text as phone, null::text as website,
         null::text as legal_name, null::text as legal_register_id, null::text as vat_number, franchise as brand_name,
         array(select lower(jsonb_array_elements_text(ops.jarr(tags)))) as cuisine_tags,
         price_range, rating_value, 0::numeric as rating_lo, 10::numeric as rating_hi, rating_count,
         null::numeric as order_minimum, null::numeric as delivery_fee, null::integer as delivery_estimate_min,
         null::boolean as is_halal, product_line, short_description as description, logo_url, cover_image_url,
         null::text as opening_hours_text, null::text as business_status, null::text as share_url
  from {{ ref('stg_wolt__venue_listing') }}
  union all
  -- wolt_static
  select 'wolt', platform_id, 'venue_static', observation_id, run_id, fetched_at,
         name, case when address_line ilike '%virtuelles Geschäft%' then null else address_line end, postcode, city,
         lat, lon, phone, case when website ~ 'wolt\.com' then null else website end,
         legal_name, legal_register_id, vat_number, brand_name,
         array(select lower(jsonb_array_elements_text(ops.jarr(food_tags))))
           || array(select lower(c ->> 'name') from jsonb_array_elements(ops.jarr(categories)) c),
         price_range, rating_value, 0, 10, rating_count,
         order_minimum, delivery_base_fee, null, null, product_line, description, logo_url, cover_image_url,
         opening_times_display::text, null, share_url
  from {{ ref('stg_wolt__venue_static') }}
  union all
  -- wolt_dyn
  select 'wolt', platform_id, 'venue_dynamic', observation_id, run_id, fetched_at,
         null, null, null, null, null::float8, null::float8, null, null, null, null, null, null,
         null::text[], null::smallint, null::numeric, 0, 10, null::integer,
         order_minimum, null, delivery_estimate_min, null, null, null, null, null, null,
         case when open_status = 'CLOSED' then 'closed_now' end, null
  from {{ ref('stg_wolt__venue_dynamic') }}
  union all
  -- lief_list
  select 'lieferando', platform_id, 'restaurant_listing', observation_id, run_id, fetched_at,
         name, address_line, postcode, city, lat, lon, null, null, null, null, null, null,
         array(select lower(c ->> 'uniqueName') from jsonb_array_elements(ops.jarr(cuisines)) c)
           || array(select lower(c ->> 'name') from jsonb_array_elements(ops.jarr(cuisines)) c),
         null::smallint, rating_value, 0, 5, rating_count,
         null, null, null,
         exists (select 1 from jsonb_array_elements(ops.jarr(cuisines)) c where c ->> 'uniqueName' like '%halal%'),
         null, null, logo_url, null, null, case when is_test then 'test' end, null
  from {{ ref('stg_lieferando__restaurant_listing') }}
  union all
  -- lief_man
  select 'lieferando', platform_id, 'menu_manifest', observation_id, run_id, fetched_at,
         name, address_line, postcode, city, lat, lon, phone, null,
         legal_name, null, vat_number, null,
         array(select lower(c ->> 'SeoName') from jsonb_array_elements(ops.jarr(cuisines)) c)
           || array(select lower(c ->> 'Name') from jsonb_array_elements(ops.jarr(cuisines)) c),
         null::smallint, null::numeric, 0, 5, null::integer,
         null, null, null, is_halal or exists (select 1 from jsonb_array_elements(ops.jarr(cuisines)) c where c ->> 'SeoName' like '%halal%'),
         storefront_type, description, logo_url, null, opening_times::text,
         case when is_offline then 'offline' end, share_url
  from {{ ref('stg_lieferando__manifest') }}
  union all
  -- gmaps
  select 'google_maps', platform_id, 'place', observation_id, run_id, fetched_at,
         name, address_line, postcode, city, lat, lon, phone, website, null, null, null, null,
         array(select lower(jsonb_array_elements_text(ops.jarr(categories)))),
         case when price_band ~ '^€+$' then length(price_band)::smallint
              when price_band ~ '^\d' then least(4, greatest(1, ceil(substring(price_band from '(\d+)\s*€?\s*$')::numeric / 15)))::smallint
         end,
         rating_value, 1, 5, rating_count,
         null, null, null,
         exists (select 1 from jsonb_array_elements_text(ops.jarr(categories)) c where c ilike '%halal%'),
         result_type, coalesce(description, short_description), image_url, null, opening_hours::text,
         business_status, null
  from {{ ref('stg_google_maps__place') }}
  union all
  -- osm
  select 'osm', platform_id, 'poi', null::uuid, null::uuid, coalesce(osm_edited_at, (dataset_version)::date::timestamptz),
         name, address_line, postcode, city, lat, lon, phone, website, null, null, null, brand,
         cuisines || array[poi_type],
         null::smallint, null::numeric, 1, 5, null::integer,
         null, null, null, diet_halal in ('yes', 'only'), poi_type, null, null, null, opening_hours,
         case when is_disused then 'closed_permanently' end, null
  from {{ ref('stg_osm__poi') }}
  union all
  -- overture
  select 'overture', platform_id, 'place', null::uuid, null::uuid, (split_part(dataset_version, '.', 1))::date::timestamptz,
         name, address_line, postcode, city, lat, lon, phone, website, null, null, null, brand,
         array[basic_category, category_primary] || array(select jsonb_array_elements_text(ops.jarr(category_alternates))),
         null::smallint, null::numeric, 1, 5, null::integer,
         null, null, null, null, basic_category, null, null, null, null,
         case when operating_status in ('permanently_closed', 'closed') then 'closed_permanently'
              when operating_status = 'temporarily_closed' then 'closed_temporarily' end, null
  from {{ ref('stg_overture__place') }}
  union all
  -- uber_eats (one-time Apify store list)
  select 'uber_eats', platform_id, 'store', observation_id, run_id, fetched_at,
         name, address_line, postcode, 'Berlin', lat, lon, null, null, null, null, null, null,
         array(select lower(replace(c, '-', ' ')) from jsonb_array_elements_text(ops.jarr(cuisines)) c),
         case when price_range between 1 and 4 then price_range end, rating_value, 1, 5, rating_count,
         null, null, null,
         exists (select 1 from jsonb_array_elements_text(ops.jarr(cuisines)) c where c ilike '%halal%'),
         null, null, null, null, null, null, share_url
  from {{ ref('stg_uber_eats__store') }}
)
select
  platform || ':' || platform_id                           as listing_key,
  md5(platform || ':' || platform_id)::uuid                as listing_id,
  u.*,
  {{ name_key('name') }}                                   as name_key,
  {{ street('address_line') }}                             as street,
  {{ house_number('address_line') }}                       as house_number,
  {{ registrable_domain('website') }}                      as website_domain,
  {{ rating_norm('rating_value', 'rating_lo', 'rating_hi') }} as rating_norm,
  {{ h3_r8('lat', 'lon') }}                                as h3_r8
from unioned u
