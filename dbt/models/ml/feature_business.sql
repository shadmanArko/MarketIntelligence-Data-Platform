{{ config(indexes=[{'columns': ['business_id'], 'unique': True}]) }}
-- Point-in-time business features: only data observed at or before var('as_of') is used, so a training row
-- never sees the future. Missing values stay NULL and get an explicit *_missing indicator for models.
{% set as_of = var('as_of', none) %}
{% set as_of_sql = "'" ~ as_of ~ "'::timestamptz" if as_of else "now()" %}
with b as (
  select b.*, g.h3_r8 from {{ ref('business') }} b join {{ ref('business_geo') }} g using (business_id)
  where b.in_market and b.first_seen_at <= {{ as_of_sql }}
),
l as (
  select a.business_id, l.listing_id, l.platform
  from ops.business_assignment a join {{ ref('listing') }} l using (listing_key)
  where l.first_seen_at <= {{ as_of_sql }}
),
snap as (  -- latest reading per listing as of the cut-off
  select distinct on (s.listing_id) l.business_id, l.platform, s.rating_norm, s.rating_count, s.order_minimum,
         s.base_delivery_fee, s.delivery_estimate_min, s.observed_at
  from {{ ref('listing_snapshot') }} s join l using (listing_id)
  where s.observed_at <= {{ as_of_sql }} and s.outlier_reason is null
  order by s.listing_id, s.observed_at desc
),
reviews as (
  select l.business_id,
         count(*) filter (where r.posted_at > {{ as_of_sql }} - interval '30 days')  as reviews_30d,
         count(*) filter (where r.posted_at > {{ as_of_sql }} - interval '90 days')  as reviews_90d,
         avg(r.rating_norm) filter (where r.posted_at > {{ as_of_sql }} - interval '90 days') as review_rating_90d,
         avg(r.has_owner_reply::int)                                                 as owner_reply_rate,
         avg(r.text_length)                                                          as review_text_length_mean
  from {{ ref('review') }} r join l using (listing_id)
  where r.posted_at <= {{ as_of_sql }}
  group by 1
),
menu as (
  select l.business_id, count(distinct o.offering_id) as menu_items, count(distinct o.dish_id) as canonical_dishes,
         percentile_cont(0.5) within group (order by p.price) as median_item_price,
         avg(p.discount_share) as mean_discount_share,
         avg((o.attributes ->> 'halal')::boolean::int) as halal_item_share,
         avg((o.attributes ->> 'vegan')::boolean::int) as vegan_item_share,
         avg((o.attributes ->> 'spicy')::boolean::int) as spicy_item_share,
         bool_or(o.dish_id like '%biryani%') as sells_biryani
  from {{ ref('offering') }} o join l using (listing_id)
  join lateral (select price, discount_share from {{ ref('offering_price_snapshot') }} ps
                where ps.offering_id = o.offering_id and ps.observed_at <= {{ as_of_sql }} and ps.outlier_reason is null
                order by ps.observed_at desc limit 1) p on true
  where o.first_seen_at <= {{ as_of_sql }}
  group by 1
),
area as (select * from {{ ref('area_demand') }}),
comp as (  -- same-cuisine competitors within ~1 km (H3 ring 2 around the cell)
  select b1.business_id, count(distinct b2.business_id) as same_cuisine_within_1km,
         count(distinct b2.business_id) filter (where b2.delivery_platform_count > 0) as same_cuisine_delivery_within_1km
  from b b1
  join b b2 on b2.business_id <> b1.business_id and b2.primary_cuisine = b1.primary_cuisine
   and b2.h3_r8 = any(array(select h3_grid_disk(b1.h3_r8::h3index, 2)::text))
  group by 1
),
brand as (select brand_id, count(*) as brand_locations from ops.brand_assignment group by 1)
select
  b.business_id,
  {{ as_of_sql }}                                                   as as_of,
  b.primary_cuisine, b.primary_cuisine_group, b.district, b.h3_r8, b.price_range, b.is_halal,
  b.brand_id is not null as is_chain, coalesce(br.brand_locations, 1) as brand_locations,
  b.on_wolt, b.on_lieferando, b.on_google_maps, b.delivery_platform_count, b.listing_count,
  extract(epoch from {{ as_of_sql }} - b.first_seen_at) / 86400.0   as days_known,
  max(s.rating_norm) filter (where s.platform = 'google_maps')     as google_rating_norm,
  max(s.rating_count) filter (where s.platform = 'google_maps')    as google_rating_count,
  max(s.rating_norm) filter (where s.platform = 'wolt')            as wolt_rating_norm,
  max(s.rating_count) filter (where s.platform = 'wolt')           as wolt_rating_count,
  max(s.rating_norm) filter (where s.platform = 'lieferando')      as lieferando_rating_norm,
  max(s.rating_count) filter (where s.platform = 'lieferando')     as lieferando_rating_count,
  min(s.order_minimum)                                              as order_minimum,
  min(s.base_delivery_fee)                                          as base_delivery_fee,
  min(s.delivery_estimate_min)                                      as delivery_estimate_min,
  rv.reviews_30d, rv.reviews_90d, rv.review_rating_90d, rv.owner_reply_rate, rv.review_text_length_mean,
  m.menu_items, m.canonical_dishes, m.median_item_price, m.mean_discount_share, m.halal_item_share,
  m.vegan_item_share, m.spicy_item_share, m.sells_biryani,
  a.population as cell_population, a.foreigner_share_pct as cell_foreigner_share_pct, a.mean_age as cell_mean_age,
  a.household_size as cell_household_size, a.rent_eur_m2 as cell_rent_eur_m2,
  a.wolt_venues_delivering as cell_wolt_venues_delivering, a.businesses as cell_businesses,
  coalesce(c.same_cuisine_within_1km, 0) as same_cuisine_within_1km,
  coalesce(c.same_cuisine_delivery_within_1km, 0) as same_cuisine_delivery_within_1km,
  -- missingness indicators (missing is information, not zero)
  max(s.rating_norm) filter (where s.platform = 'google_maps') is null as google_rating_missing,
  m.menu_items is null                                              as menu_missing,
  rv.reviews_90d is null                                            as reviews_missing,
  b.price_range is null                                             as price_range_missing
from b
left join snap s using (business_id)
left join reviews rv using (business_id)
left join menu m using (business_id)
left join area a on a.h3_r8 = b.h3_r8
left join comp c using (business_id)
left join brand br using (brand_id)
group by b.business_id, b.primary_cuisine, b.primary_cuisine_group, b.district, b.h3_r8, b.price_range, b.is_halal,
         b.brand_id, br.brand_locations, b.on_wolt, b.on_lieferando, b.on_google_maps, b.delivery_platform_count,
         b.listing_count, b.first_seen_at, rv.reviews_30d, rv.reviews_90d, rv.review_rating_90d, rv.owner_reply_rate,
         rv.review_text_length_mean, m.menu_items, m.canonical_dishes, m.median_item_price, m.mean_discount_share,
         m.halal_item_share, m.vegan_item_share, m.spicy_item_share, m.sells_biryani, a.population,
         a.foreigner_share_pct, a.mean_age, a.household_size, a.rent_eur_m2, a.wolt_venues_delivering, a.businesses,
         c.same_cuisine_within_1km, c.same_cuisine_delivery_within_1km
