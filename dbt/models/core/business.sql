{{ config(materialized='table', indexes=[{'columns': ['business_id'], 'unique': True}, {'columns': ['brand_id']}]) }}
-- One real-world business across all platforms (ids owned by the resolution job: ops.business_assignment).
-- Field precedence: the platform most likely to be right for that field.
{% set prec = "case l.platform when 'google_maps' then 1 when 'wolt' then 2 when 'lieferando' then 3 when 'osm' then 4 else 5 end" %}
with m as (
  select a.business_id, a.match_prob, a.method, l.*
  from ops.business_assignment a join {{ ref('listing') }} l using (listing_key)
),
cuisine as (
  select m.business_id, c.cuisine_id, c.cuisine_group, sum(c.tag_hits) as hits
  from m join {{ ref('listing_cuisine') }} c using (listing_id)
  group by 1, 2, 3
),
cuisine_ranked as (
  select business_id,
         (array_agg(cuisine_id order by hits desc, cuisine_id))[1]     as primary_cuisine,
         (array_agg(cuisine_group order by hits desc, cuisine_id))[1]  as primary_cuisine_group,
         array_agg(cuisine_id order by hits desc, cuisine_id)          as cuisines
  from cuisine group by 1
)
select
  m.business_id,
  (array_agg(m.name order by {{ prec | replace('l.', 'm.') }}, m.observation_count desc))[1] as name,
  (array_agg(m.name_key order by {{ prec | replace('l.', 'm.') }}) filter (where m.name_key is not null))[1] as name_key,
  (array_agg(m.lat order by {{ prec | replace('l.', 'm.') }}) filter (where m.lat is not null))[1] as lat,
  (array_agg(m.lon order by {{ prec | replace('l.', 'm.') }}) filter (where m.lon is not null))[1] as lon,
  (array_agg(m.address_line order by {{ prec | replace('l.', 'm.') }}) filter (where m.address_line is not null))[1] as address_line,
  (array_agg(m.street order by {{ prec | replace('l.', 'm.') }}) filter (where m.street is not null))[1] as street,
  (array_agg(m.house_number order by {{ prec | replace('l.', 'm.') }}) filter (where m.house_number is not null))[1] as house_number,
  (array_agg(m.postcode_resolved order by {{ prec | replace('l.', 'm.') }}) filter (where m.postcode_resolved is not null))[1] as postcode,
  (array_agg(m.district) filter (where m.district is not null))[1]   as district,
  (array_agg(m.locality) filter (where m.locality is not null))[1]   as locality,
  (array_agg(m.planning_area_id order by {{ prec | replace('l.', 'm.') }}) filter (where m.planning_area_id is not null))[1] as planning_area_id,
  (array_agg(m.planning_area order by {{ prec | replace('l.', 'm.') }}) filter (where m.planning_area is not null))[1] as planning_area,
  (array_agg(m.phone order by {{ prec | replace('l.', 'm.') }}) filter (where m.phone is not null))[1] as phone,
  (array_agg(m.website order by {{ prec | replace('l.', 'm.') }}) filter (where m.website is not null and m.website !~ '(wolt|lieferando|ubereats)\.'))[1] as website,
  (array_agg(m.website_domain order by {{ prec | replace('l.', 'm.') }}) filter (where m.website_domain is not null))[1] as website_domain,
  (array_agg(m.legal_name) filter (where m.legal_name is not null))[1] as legal_name,
  (array_agg(m.legal_register_id) filter (where m.legal_register_id is not null))[1] as legal_register_id,
  (array_agg(m.vat_number) filter (where m.vat_number is not null))[1] as vat_number,
  (array_agg(m.price_range order by {{ prec | replace('l.', 'm.') }}) filter (where m.price_range is not null))[1] as price_range,
  bool_or(m.is_halal)                                      as is_halal,
  cr.primary_cuisine, cr.primary_cuisine_group, cr.cuisines,
  ba.brand_id, ba.brand_name,
  bool_or(m.platform = 'wolt')                             as on_wolt,
  bool_or(m.platform = 'lieferando')                       as on_lieferando,
  bool_or(m.platform = 'uber_eats')                        as on_uber_eats,
  bool_or(m.platform = 'google_maps')                      as on_google_maps,
  bool_or(m.platform = 'osm')                              as in_osm,
  bool_or(m.platform = 'overture')                         as in_overture,
  count(*) filter (where m.platform in ('wolt', 'lieferando', 'uber_eats')) as delivery_platform_count,
  count(*)                                                 as listing_count,
  array_agg(m.listing_key order by m.platform)             as listing_keys,
  case when bool_and(m.status in ('closed_permanently', 'offline')) then 'closed'
       when bool_or(m.status = 'active' and m.platform in ('wolt', 'lieferando', 'google_maps')) then 'active'
       when bool_or(m.status = 'closed_temporarily') then 'closed_temporarily'
       else 'unverified' end                               as status,
  bool_or(m.in_market)                                     as in_market,
  min(m.first_seen_at)                                     as first_seen_at,
  max(m.last_seen_at)                                      as last_seen_at,
  min(m.match_prob)                                        as min_match_prob
from m
left join cuisine_ranked cr using (business_id)
left join ops.brand_assignment ba using (business_id)
group by m.business_id, cr.primary_cuisine, cr.primary_cuisine_group, cr.cuisines, ba.brand_id, ba.brand_name
