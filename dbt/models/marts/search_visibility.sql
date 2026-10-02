-- Google Maps visibility: for every query x area, which business ranked where (the map results people see).
-- Share of search = rank-weighted visibility (CTR-like 1/rank weights) summed per business and query.
with r as (
  select s.query, s.cell, s.rank, s.fetched_at as observed_at, a.business_id
  from {{ ref('stg_google_maps__search_result') }} s
  join ops.business_assignment a on a.listing_key = 'google_maps:' || s.platform_id
),
w as (select *, 1.0 / (rank + 1) as weight from r)
select business_id, query, count(distinct cell) as cells_visible, min(rank) as best_rank,
       round(avg(rank)::numeric, 1) as avg_rank, sum(weight) as visibility,
       sum(weight) / sum(sum(weight)) over (partition by query) as share_of_search
from w group by 1, 2
