{{ config(materialized='table', indexes=[{'columns': ['offering_id', 'observed_at']}]) }}
-- Offering x observation: base price, original (pre-discount) price, size range, deposit.
-- Outliers are flagged with a reason, never deleted (placeholder prices, cents typed as euros, non-food stock).
with s as (
  select distinct on (offering_id, run_id, price, original_price, price_max)
    offering_id, listing_id, platform, run_id, observed_at,
    price, original_price, price_max, deposit, currency,
    case when original_price is not null and original_price > price then round(1 - price / original_price, 4) end as discount_share,
    size_variants
  from {{ ref('int_offering_observation') }}
  where price is not null
  order by offering_id, run_id, price, original_price, price_max, observed_at
),
med as (select listing_id, percentile_cont(0.5) within group (order by price) as listing_median from s group by 1)
select s.*, m.listing_median,
  case when s.price in (999, 999.99, 9999, 9999.99, 99999) then 'placeholder_price'
       when s.price > 20 * m.listing_median and s.price > 60 then 'far_above_listing_median'
       when s.price > 500 then 'above_500_eur'
       when s.price = 0 then 'zero_price' end                as outlier_reason
from s join med m using (listing_id)
