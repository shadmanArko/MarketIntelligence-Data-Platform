{{ config(materialized='table', indexes=[{'columns': ['listing_id']}, {'columns': ['cuisine_id']}]) }}
-- Every platform tag mapped onto the unified cuisine taxonomy (seed cuisine_map, from config/taxonomies).
with tags as (
  select l.listing_id, l.platform, t as source_tag, {{ fold('t') }} as tag
  from {{ ref('listing') }} l, unnest(l.source_tags) t
),
matched as (
  select t.listing_id, t.platform, t.source_tag, m.cuisine_id, m.cuisine_group,
         case when t.tag = m.tag then 'exact' else 'contains' end as match_type
  from tags t
  join {{ ref('cuisine_map') }} m
    on t.tag = m.tag
    or (length(m.tag) >= 5 and t.tag ~ ('\m' || m.tag))
    or (length(m.tag) <  5 and t.tag ~ ('\m' || m.tag || '\M'))
)
select listing_id, cuisine_id, min(cuisine_group) as cuisine_group, count(*) as tag_hits,
       bool_or(match_type = 'exact') as exact_match, array_agg(distinct source_tag) as source_tags
from matched
group by 1, 2
