{{ config(materialized='table', indexes=[{'columns': ['listing_id'], 'unique': True}, {'columns': ['platform']},
                                          {'columns': ['h3_r8']}, {'columns': ['geog'], 'type': 'gist'}]) }}
-- One business on one platform, current state: per attribute the latest non-null value across all
-- observations of that listing (venue list, venue page, menu manifest, ...). History: core.listing_history.
{% set latest = ['name', 'name_key', 'address_line', 'street', 'house_number', 'postcode', 'city', 'phone', 'website',
                 'website_domain', 'legal_name', 'legal_register_id', 'vat_number', 'brand_name', 'price_range',
                 'product_line', 'description', 'logo_url', 'cover_image_url', 'opening_hours_text', 'share_url'] %}
with agg as (
  select
    listing_key, listing_id, platform, platform_id,
    {% for c in latest %}(array_agg({{ c }} order by observed_at desc) filter (where {{ c }} is not null
      {%- if c == 'price_range' %} and price_range between 1 and 4{% endif %}))[1] as {{ c }},
    {% endfor %}
    (array_agg(lat order by (obs_kind in ('venue_static', 'menu_manifest', 'place', 'poi')) desc, observed_at desc)
       filter (where lat is not null))[1] as lat,
    (array_agg(lon order by (obs_kind in ('venue_static', 'menu_manifest', 'place', 'poi')) desc, observed_at desc)
       filter (where lon is not null))[1] as lon,
    bool_or(is_halal)                                      as is_halal,
    array(select distinct t from unnest(ops.array_cat_agg(cuisine_tags)) t where t is not null and t <> '') as source_tags,
    (array_agg(business_status order by observed_at desc))[1] as last_status,
    min(observed_at)                                       as first_seen_at,
    max(observed_at)                                       as last_seen_at,
    count(*)                                               as observation_count
  from {{ ref('int_listing_observation') }}
  group by 1, 2, 3, 4
)
select
  a.*,
  case when a.last_status in ('closed_permanently', 'offline', 'test') then a.last_status
       when a.last_status = 'closed_temporarily' then 'closed_temporarily'
       else 'active' end                                   as status,
  {{ geog('a.lat', 'a.lon') }}                             as geog,
  {{ h3_r8('a.lat', 'a.lon') }}                            as h3_r8,
  coalesce(st_covers(m.geom, st_setsrid(st_makepoint(a.lon, a.lat), 4326)), false) as in_market,
  d.name                                                   as district,
  lo.name                                                  as locality,
  coalesce(a.postcode, pc.code)                            as postcode_resolved
from agg a
left join raw.geo_area m  on m.kind = 'market'   and m.market_id = '{{ var("market_id") }}'
left join raw.geo_area d  on d.kind = 'district' and st_covers(d.geom, st_setsrid(st_makepoint(a.lon, a.lat), 4326))
left join raw.geo_area lo on lo.kind = 'locality' and st_covers(lo.geom, st_setsrid(st_makepoint(a.lon, a.lat), 4326))
left join raw.geo_area pc on pc.kind = 'postcode' and st_covers(pc.geom, st_setsrid(st_makepoint(a.lon, a.lat), 4326))
