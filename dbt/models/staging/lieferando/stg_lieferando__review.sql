-- One row per review (reviewer identity is already a salted hash in raw).
with src as {{ raw_entity('lieferando', 'reviews') }},
r as (
  select s.observation_id, s.run_id, s.fetched_at, s.request_meta ->> 'restaurant_id' as platform_id, e.value as v
  from src s, jsonb_array_elements(ops.jarr(s.payload -> 'reviews')) e
)
select distinct on (v ->> 'reviewId')
  observation_id, run_id, fetched_at, platform_id,
  v ->> 'reviewId'                                         as review_platform_id,
  v ->> 'customerName'                                     as reviewer_hash,
  (v ->> 'rateDate')::timestamptz                          as posted_at,
  (v ->> 'ratingAverage')::numeric(3,1)                    as rating_value,
  (v ->> 'maxRating')::numeric(3,1)                        as rating_scale_max,
  {{ clean_text("v ->> 'customerComments'") }}             as text,
  {{ clean_text("v ->> 'restaurantComments'") }}           as owner_reply,
  v                                                        as attributes
from r
order by v ->> 'reviewId', fetched_at desc
