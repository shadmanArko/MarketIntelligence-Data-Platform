{{ config(indexes=[{'columns': ['business_id'], 'unique': True}, {'columns': ['primary_cuisine']}]) }}
-- One row per Berlin business: where it is, what it sells, how it rates and what ordering costs, per platform.
with latest_snap as (
  select distinct on (s.listing_id) s.listing_id, s.platform, s.rating_value, s.rating_norm, s.rating_count,
         s.observed_at
  from {{ ref('listing_snapshot') }} s where s.rating_value is not null
  order by s.listing_id, s.observed_at desc
),
fees as (
  select distinct on (listing_id) listing_id, order_minimum, base_delivery_fee, delivery_estimate_min
  from {{ ref('listing_snapshot') }} where coalesce(order_minimum, base_delivery_fee) is not null and outlier_reason is null
  order by listing_id, observed_at desc
),
menu as (
  select o.listing_id, count(*) as menu_items, count(distinct o.dish_id) as canonical_dishes,
         percentile_cont(0.5) within group (order by p.price) as median_item_price,
         array_agg(distinct o.dish_id) filter (where o.dish_id is not null) as dishes,
         avg((o.attributes ->> 'halal')::boolean::int) as halal_item_share,
         avg((o.attributes ->> 'vegan')::boolean::int) as vegan_item_share
  from {{ ref('offering') }} o
  join lateral (select price from {{ ref('offering_price_snapshot') }} ps
                where ps.offering_id = o.offering_id and ps.outlier_reason is null order by observed_at desc limit 1) p on true
  where coalesce((o.attributes ->> 'drink')::boolean, false) = false
  group by 1
),
coverage as (
  select listing_id, count(distinct area_id) as delivery_areas
  from {{ ref('coverage_observation') }} where offered group by 1
),
per_listing as (
  select a.business_id, l.platform, ls.rating_value, ls.rating_norm, ls.rating_count, f.order_minimum,
         f.base_delivery_fee, f.delivery_estimate_min, m.menu_items, m.canonical_dishes, m.median_item_price, m.dishes,
         m.halal_item_share, m.vegan_item_share, cv.delivery_areas
  from ops.business_assignment a join {{ ref('listing') }} l using (listing_key)
  left join latest_snap ls using (listing_id) left join fees f using (listing_id)
  left join menu m using (listing_id) left join coverage cv using (listing_id)
),
crux as (
  select regexp_replace(origin, '^https?://(www\.)?', '') as domain, min(rank_bucket) as best_rank_bucket
  from raw.ds_crux_rank where yyyymm = (select max(yyyymm) from raw.ds_crux_rank) group by 1
)
select
  b.business_id, b.name, b.brand_name, b.primary_cuisine, b.primary_cuisine_group, b.cuisines, b.is_halal,
  b.district, b.locality, b.postcode, b.address_line, b.lat, b.lon, g.h3_r8, b.price_range, b.status,
  b.phone, b.website, b.website_domain, cx.best_rank_bucket as crux_rank_bucket,
  b.on_wolt, b.on_lieferando, b.on_google_maps, b.delivery_platform_count,
  max(p.rating_value) filter (where p.platform = 'google_maps')      as google_rating,
  max(p.rating_count) filter (where p.platform = 'google_maps')      as google_review_count,
  max(p.rating_value) filter (where p.platform = 'wolt')             as wolt_rating,
  max(p.rating_count) filter (where p.platform = 'wolt')             as wolt_rating_count,
  max(p.rating_value) filter (where p.platform = 'lieferando')       as lieferando_rating,
  max(p.rating_count) filter (where p.platform = 'lieferando')       as lieferando_rating_count,
  sum(p.rating_norm * p.rating_count) / nullif(sum(p.rating_count) filter (where p.rating_norm is not null), 0) as rating_norm_weighted,
  sum(p.rating_count)                                                as rating_count_total,
  min(p.order_minimum)                                               as min_order_minimum,
  min(p.base_delivery_fee)                                           as min_base_delivery_fee,
  min(p.delivery_estimate_min)                                       as min_delivery_estimate_min,
  max(p.menu_items)                                                  as menu_items,
  max(p.canonical_dishes)                                            as canonical_dishes,
  avg(p.median_item_price)::numeric(10,2)                            as median_item_price,
  max(p.halal_item_share)                                            as halal_item_share,
  max(p.vegan_item_share)                                            as vegan_item_share,
  max(p.delivery_areas)                                              as delivery_areas_max,
  b.listing_count, b.first_seen_at, b.last_seen_at
from {{ ref('business') }} b
join {{ ref('business_geo') }} g using (business_id)
left join per_listing p using (business_id)
left join crux cx on cx.domain = b.website_domain
where b.in_market
group by b.business_id, b.name, b.brand_name, b.primary_cuisine, b.primary_cuisine_group, b.cuisines, b.is_halal,
         b.district, b.locality, b.postcode, b.address_line, b.lat, b.lon, g.h3_r8, b.price_range, b.status, b.phone,
         b.website, b.website_domain, cx.best_rank_bucket, b.on_wolt, b.on_lieferando, b.on_google_maps,
         b.delivery_platform_count, b.listing_count, b.first_seen_at, b.last_seen_at
