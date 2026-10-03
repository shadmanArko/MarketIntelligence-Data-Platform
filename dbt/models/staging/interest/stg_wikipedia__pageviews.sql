-- Daily Wikipedia page views per article (latest observation of each article wins).
with latest as (
  select distinct on (natural_key) observation_id, fetched_at, payload
  from {{ raw_entity('wikipedia', 'pageviews') }} s
  order by natural_key, fetched_at desc
)
select l.payload ->> 'seed' as topic, l.payload ->> 'lang' as lang, l.payload ->> 'project' as project,
       l.payload ->> 'title' as article, to_date(left(i.value ->> 'timestamp', 8), 'YYYYMMDD') as day,
       (i.value ->> 'views')::integer as views, l.fetched_at as observed_at
from latest l, jsonb_array_elements(ops.jarr(l.payload -> 'items')) i
