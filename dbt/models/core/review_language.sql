{{ config(materialized='table') }}
-- Placeholder filled by `mip enrich languages` (lingua) into ops.text_language; joined here for dbt lineage.
select r.review_id, l.lang, l.confidence
from {{ ref('review') }} r
join ops.text_language l on l.text_kind = 'review' and l.text_id = r.review_id::text
