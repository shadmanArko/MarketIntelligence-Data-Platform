{{ config(indexes=[{'columns': ['domain'], 'unique': True}]) }}
-- One website (registrable domain): which business it belongs to, what kind of site, crawl status.
with pages as (select * from {{ ref('stg_web__page') }}),
own as (  -- a domain listed on a business's own listings belongs to that business
  select website_domain as domain, (array_agg(business_id order by listing_count desc))[1] as business_id
  from {{ ref('business') }} where website_domain is not null group by 1
)
select coalesce(o.domain, p.domain) as domain,
       o.business_id,
       case when o.business_id is not null then 'restaurant'
            when max(p.site_kind) = 'media' then 'media'
            else 'other' end                                as kind,
       count(p.*)                                           as pages_crawled,
       count(*) filter (where p.status between 200 and 299) as pages_ok,
       bool_or(p.blocked_by_robots)                         as robots_blocked,
       bool_and(p.error is not null)                        as unreachable,
       max(p.fetched_at)                                    as last_crawled_at,
       array_agg(distinct pr) filter (where pr is not null) as ordering_providers
from own o
full join pages p on p.domain = o.domain
left join lateral jsonb_array_elements_text(ops.jarr(p.ordering_providers)) pr on true
group by 1, 2
