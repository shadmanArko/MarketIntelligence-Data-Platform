{{ config(indexes=[{'columns': ['h3_r8'], 'unique': True}]) }}
-- Per H3 res-8 cell: who lives there (Zensus 2022), who can deliver there, and same-cuisine competition.
with pop as (
  select area_id as h3_r8,
         max(value) filter (where variable = 'population.einwohner')                         as population,
         max(value) filter (where variable = 'foreigner_share.anteilauslaender')             as foreigner_share_pct,
         max(value) filter (where variable = 'mean_age.durchschnittsalter')                  as mean_age,
         max(value) filter (where variable = 'household_size_mean.durchschnhhgroesse')       as household_size,
         max(value) filter (where variable = 'rent_net_cold.durchschnmieteqm')               as rent_eur_m2,
         max(value) filter (where variable = 'share_under_18.anteilunter18')                 as share_under_18_pct,
         max(value) filter (where variable = 'share_65_plus.anteilueber65')                  as share_65_plus_pct
  from {{ ref('area_stat') }} group by 1
),
supply as (
  select g.h3_r8, count(*) as businesses,
         count(*) filter (where b.primary_cuisine_group = 'south_asian') as south_asian_businesses,
         count(*) filter (where b.primary_cuisine in ('bangladeshi')) as bangladeshi_businesses,
         count(*) filter (where b.is_halal) as halal_businesses,
         count(*) filter (where b.delivery_platform_count > 0) as delivery_businesses
  from {{ ref('business') }} b join {{ ref('business_geo') }} g using (business_id)
  where b.in_market and b.status <> 'closed' group by 1
),
reach as (  -- how many distinct Wolt venues deliver to this cell (latest sweep)
  select c.area_id as h3_r8, count(distinct c.listing_id) as wolt_venues_delivering,
         count(distinct c.listing_id) filter (where lc.cuisine_group = 'south_asian') as south_asian_venues_delivering
  from {{ ref('coverage_observation') }} c
  left join (select listing_id, min(cuisine_group) cuisine_group from {{ ref('listing_cuisine') }}
             where cuisine_group = 'south_asian' group by 1) lc using (listing_id)
  where c.platform = 'wolt' and c.offered group by 1
)
select h.cell as h3_r8, h.lat, h.lon,
       p.population, p.foreigner_share_pct, p.mean_age, p.household_size, p.rent_eur_m2,
       p.share_under_18_pct, p.share_65_plus_pct,
       coalesce(s.businesses, 0) as businesses, coalesce(s.south_asian_businesses, 0) as south_asian_businesses,
       coalesce(s.bangladeshi_businesses, 0) as bangladeshi_businesses, coalesce(s.halal_businesses, 0) as halal_businesses,
       coalesce(s.delivery_businesses, 0) as delivery_businesses,
       r.wolt_venues_delivering, r.south_asian_venues_delivering,
       case when r.south_asian_venues_delivering > 0
            then round((p.population / r.south_asian_venues_delivering)::numeric, 1) end as residents_per_south_asian_venue
from raw.geo_h3 h
left join pop p on p.h3_r8 = h.cell
left join supply s on s.h3_r8 = h.cell
left join reach r on r.h3_r8 = h.cell
where h.res = 8 and h.in_market
