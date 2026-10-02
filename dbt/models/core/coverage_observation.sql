{{ config(materialized='table', indexes=[{'columns': ['listing_id']}, {'columns': ['area_id']}]) }}
-- Listing x area (H3 grid cell or postcode) x observation: offered there, with fee / estimate at that point.
select md5('wolt:' || platform_id)::uuid as listing_id, 'wolt' as platform, 'h3_r8' as area_type, cell as area_id,
       point_lat, point_lon, run_id, fetched_at as observed_at, list_position, delivers as offered, online as open_now,
       null::numeric(10,2) as delivery_fee, null::numeric(10,2) as order_minimum,
       delivery_estimate_min as eta_min_lower, delivery_estimate_min as eta_min_upper, null::integer as distance_m,
       delivery_price_rank, null::integer as promoted_rank, jsonb_array_length(promotions) as promotion_count, wolt_plus
from {{ ref('stg_wolt__coverage') }}
union all
select md5('lieferando:' || platform_id)::uuid, 'lieferando', 'postcode', postcode,
       point_lat, point_lon, run_id, fetched_at, list_position, true, open_now_delivery,
       delivery_fee, order_minimum, eta_min_lower, eta_min_upper, distance_m,
       null, promoted_rank, jsonb_array_length(deals), null
from {{ ref('stg_lieferando__coverage') }}
