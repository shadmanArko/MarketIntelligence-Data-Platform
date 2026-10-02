{{ config(materialized='table', indexes=[{'columns': ['listing_id', 'observed_at']}]) }}
-- Moving numbers, one row per listing x observation (consecutive identical readings within a run collapse).
with m as (
  select listing_id, listing_key, platform, obs_kind, run_id, observed_at,
         rating_value, rating_lo as rating_scale_min, rating_hi as rating_scale_max, rating_norm, rating_count,
         order_minimum, delivery_fee as base_delivery_fee, delivery_estimate_min, business_status
  from {{ ref('int_listing_observation') }}
  where coalesce(rating_value, rating_count, order_minimum, delivery_fee, delivery_estimate_min) is not null
     or business_status is not null
),
d as (
  select *, {{ attr_hash(['rating_value', 'rating_count', 'order_minimum', 'base_delivery_fee', 'delivery_estimate_min',
                          'business_status']) }} as h
  from m
)
select distinct on (listing_id, obs_kind, coalesce(run_id::text, observed_at::text), h)
  listing_id, listing_key, platform, obs_kind as observed_via, run_id, observed_at,
  rating_value, rating_scale_min, rating_scale_max, rating_norm, rating_count,
  order_minimum, base_delivery_fee, delivery_estimate_min, business_status, 'EUR' as currency,
  case when base_delivery_fee > 30 or order_minimum > 150 then 'catering_or_error' end as outlier_reason
from d
order by listing_id, obs_kind, coalesce(run_id::text, observed_at::text), h, observed_at
