-- Price index per canonical dish: each offering vs the Berlin median for that dish (latest clean prices).
with p as (
  select o.offering_id, o.listing_id, o.platform, o.dish_id, o.name, a.business_id,
         (select price from {{ ref('offering_price_snapshot') }} ps where ps.offering_id = o.offering_id
            and ps.outlier_reason is null order by observed_at desc limit 1) as price
  from {{ ref('offering') }} o
  join {{ ref('listing') }} l using (listing_id)
  join ops.business_assignment a on a.listing_key = l.listing_key
  where o.dish_id is not null and l.in_market
),
berlin as (
  select dish_id, count(*) n, percentile_cont(0.5) within group (order by price) as median_price,
         percentile_cont(0.25) within group (order by price) as p25, percentile_cont(0.75) within group (order by price) as p75
  from p where price is not null group by 1
)
select p.business_id, p.listing_id, p.platform, p.offering_id, p.dish_id, p.name, p.price,
       b.median_price::numeric(10,2) as berlin_median_price, b.p25::numeric(10,2) as berlin_p25,
       b.p75::numeric(10,2) as berlin_p75, b.n as berlin_offerings,
       round((p.price / nullif(b.median_price, 0))::numeric, 3) as price_index
from p join berlin b using (dish_id)
where p.price is not null
