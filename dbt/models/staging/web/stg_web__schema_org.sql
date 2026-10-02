-- schema.org entities found on pages (Restaurant / LocalBusiness / Menu / Offer / AggregateRating ...).
with p as (select * from {{ ref('stg_web__page') }} where jsonld is not null)
select p.observation_id, p.fetched_at, p.url_canonical, p.domain, p.seed_business_id,
       e.value ->> '@type'                                 as schema_type,
       e.value ->> 'name'                                  as name,
       e.value ->> 'telephone'                             as telephone,
       e.value #>> '{address,streetAddress}'               as street_address,
       e.value #>> '{address,postalCode}'                  as postal_code,
       e.value ->> 'servesCuisine'                         as serves_cuisine,
       e.value ->> 'priceRange'                            as price_range,
       (e.value #>> '{aggregateRating,ratingValue}')       as rating_value,
       (e.value #>> '{aggregateRating,reviewCount}')       as review_count,
       e.value -> 'hasMenu'                                as has_menu,
       e.value -> 'openingHoursSpecification'              as opening_hours,
       e.value -> 'sameAs'                                 as same_as,
       e.value                                             as entity
from p, jsonb_array_elements(ops.jarr(p.jsonld)) e
