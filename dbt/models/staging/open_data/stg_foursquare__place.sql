-- Food-related Foursquare Open Source Places (latest registered release), every column kept.
select
  fsq_place_id                                             as platform_id,
  {{ dataset_version('foursquare_os_places') }}            as dataset_version,
  {{ clean_text('name') }}                                 as name,
  latitude::float8                                         as lat,
  longitude::float8                                        as lon,
  {{ clean_text('address') }}                              as address_line,
  postcode, locality as city,
  {{ phone_e164('tel') }}                                  as phone,
  {{ clean_url('website') }}                               as website,
  instagram, facebook_id, twitter,
  date_created::date                                       as date_created,
  date_refreshed::date                                     as date_refreshed,
  date_closed::date                                        as date_closed,
  fsq_category_labels::jsonb                               as category_labels
from {{ dataset_table('foursquare_os_places') }}
where fsq_category_labels::text ilike '%Dining and Drinking%'
   or fsq_category_labels::text ~* '(restaurant|caf[eé]|bakery|food|bar|imbiss|pizza|coffee)'
