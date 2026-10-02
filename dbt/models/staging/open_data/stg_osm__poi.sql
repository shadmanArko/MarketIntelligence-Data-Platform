-- Food-related OpenStreetMap POIs (latest registered Berlin extract), all tags kept.
select
  osm_type || '/' || osm_id                                as platform_id,
  {{ dataset_version('osm_berlin_pois') }}                 as dataset_version,
  timestamp                                                as osm_edited_at,
  {{ clean_text('name') }}                                 as name,
  lat, lon,
  coalesce(tags ->> 'amenity', tags ->> 'shop')            as poi_type,
  tags ->> 'cuisine'                                       as cuisine_raw,
  string_to_array(replace(lower(tags ->> 'cuisine'), ' ', ''), ';') as cuisines,
  {{ clean_text("concat_ws(' ', tags ->> 'addr:street', tags ->> 'addr:housenumber')") }} as address_line,
  tags ->> 'addr:postcode'                                 as postcode,
  coalesce(tags ->> 'addr:city', 'Berlin')                 as city,
  {{ clean_url("coalesce(tags ->> 'website', tags ->> 'contact:website', tags ->> 'url')") }} as website,
  {{ phone_e164("coalesce(tags ->> 'phone', tags ->> 'contact:phone')") }} as phone,
  coalesce(tags ->> 'contact:instagram', tags ->> 'instagram')  as instagram,
  coalesce(tags ->> 'contact:facebook', tags ->> 'facebook')    as facebook,
  tags ->> 'opening_hours'                                 as opening_hours,
  tags ->> 'brand'                                         as brand,
  tags ->> 'brand:wikidata'                                as brand_wikidata,
  tags ->> 'diet:halal'                                    as diet_halal,
  tags ->> 'diet:vegan'                                    as diet_vegan,
  tags ->> 'diet:vegetarian'                               as diet_vegetarian,
  tags ->> 'delivery'                                      as delivery,
  tags ->> 'takeaway'                                      as takeaway,
  tags ->> 'outdoor_seating'                               as outdoor_seating,
  tags ->> 'wheelchair'                                    as wheelchair,
  tags ->> 'capacity'                                      as capacity,
  tags ->> 'disused:amenity' is not null or tags ? 'was:amenity' as is_disused,
  tags
from {{ dataset_table('osm_berlin_pois') }}
where (tags ->> 'amenity' in ('restaurant','fast_food','cafe','food_court','bar','pub','biergarten','ice_cream')
       or tags ->> 'shop' in ('deli','bakery','pastry','confectionery','butcher','greengrocer','seafood')
       or tags ? 'cuisine')
  and name is not null
