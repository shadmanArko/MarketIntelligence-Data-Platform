-- TripAdvisor European Restaurants (Kaggle, scraped 2021-05): Berlin rows, a dated baseline.
select
  regexp_replace(restaurant_link, '^.*-d(\d+)-.*$', 'd\1')  as platform_id,
  date '2021-05-18'                                        as observed_on,
  {{ clean_text('restaurant_name') }}                      as name,
  {{ clean_text("split_part(address, ',', 1)") }}          as address_line,
  {{ postcode('address') }}                                as postcode,
  nullif(latitude, '')::float8                             as lat,
  nullif(longitude, '')::float8                            as lon,
  nullif(avg_rating, '')::float8::numeric(3,2)             as rating_value,          -- 1-5
  nullif(total_reviews_count, '')::float8::integer         as rating_count,
  length(nullif(regexp_replace(coalesce(price_level, ''), '[^€$]', '', 'g'), ''))::smallint as price_range,
  string_to_array(lower(coalesce(cuisines, '')), ', ')     as cuisines,
  nullif(awards, '')                                       as awards,
  nullif(claimed, '')                                      as claimed,
  nullif(popularity_generic, '')                           as popularity,
  nullif(food, '')::float8                                 as score_food,
  nullif(service, '')::float8                              as score_service,
  nullif(value, '')::float8                                as score_value,
  nullif(atmosphere, '')::float8                           as score_atmosphere,
  nullif(open_hours_per_week, '')::float8                  as open_hours_per_week,
  restaurant_link                                          as share_url
from {{ dataset_table('tripadvisor_eu_restaurants') }}
