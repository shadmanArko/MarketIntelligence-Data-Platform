{{ config(materialized='table', indexes=[{'columns': ['offering_id', 'observed_at']}]) }}
-- Offering x observation: base price, original (pre-discount) price, size range, deposit.
select distinct on (offering_id, run_id, price, original_price, price_max)
  offering_id, listing_id, platform, run_id, observed_at,
  price, original_price, price_max, deposit, currency,
  case when original_price is not null and original_price > price then round(1 - price / original_price, 4) end as discount_share,
  size_variants
from {{ ref('int_offering_observation') }}
where price is not null
order by offering_id, run_id, price, original_price, price_max, observed_at
