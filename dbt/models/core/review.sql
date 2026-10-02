{{ config(materialized='table', indexes=[{'columns': ['listing_id']}, {'columns': ['posted_at']}]) }}
-- One review on any platform. Reviewer identity is a salted hash (never the name).
select
  md5('lieferando:' || review_platform_id)::uuid           as review_id,
  md5('lieferando:' || platform_id)::uuid                  as listing_id,
  'lieferando'                                             as platform,
  review_platform_id, reviewer_hash, posted_at,
  rating_value, 1::numeric as rating_scale_min, rating_scale_max,
  {{ rating_norm('rating_value', 1, 'rating_scale_max') }} as rating_norm,
  text, owner_reply, owner_reply is not null               as has_owner_reply,
  length(text)                                             as text_length,
  fetched_at                                               as observed_at
from {{ ref('stg_lieferando__review') }}
