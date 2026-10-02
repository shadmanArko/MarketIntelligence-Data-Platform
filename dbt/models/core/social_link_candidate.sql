{{ config(indexes=[{'columns': ['platform', 'handle']}]) }}
-- Candidate (business, social account) links with the evidence that proposed them.
with web as (
  select p.seed_business_id as business_id, s.key as platform, lower(h.value) as handle, 'own_website' as evidence,
         p.url_canonical as evidence_ref
  from {{ ref('stg_web__page') }} p, jsonb_each(coalesce(p.social_links, '{}'::jsonb)) s,
       jsonb_array_elements_text(ops.jarr(s.value)) h
  where p.site_kind = 'business' and p.seed_business_id is not null
),
osm as (
  select a.business_id, 'instagram', lower(regexp_replace(o.instagram, '^.*instagram\.com/|/.*$|@|\?.*$', '', 'g')),
         'osm_tag', o.platform_id
  from {{ ref('stg_osm__poi') }} o join ops.business_assignment a on a.listing_key = 'osm:' || o.platform_id
  where o.instagram is not null
  union all
  select a.business_id, 'facebook', lower(regexp_replace(o.facebook, '^.*facebook\.com/|/.*$|\?.*$', '', 'g')),
         'osm_tag', o.platform_id
  from {{ ref('stg_osm__poi') }} o join ops.business_assignment a on a.listing_key = 'osm:' || o.platform_id
  where o.facebook is not null
),
overture as (
  select a.business_id,
         case when s ~ 'facebook' then 'facebook' when s ~ 'instagram' then 'instagram' else 'other' end,
         lower(regexp_replace(s, '^.*(facebook|instagram)\.com/|/.*$|\?.*$', '', 'g')), 'overture_socials', o.platform_id
  from {{ ref('stg_overture__place') }} o join ops.business_assignment a on a.listing_key = 'overture:' || o.platform_id,
       jsonb_array_elements_text(ops.jarr(o.socials)) s
),
u as (select * from web union all select * from osm union all select * from overture)
select business_id, platform, handle, array_agg(distinct evidence) as evidence, count(*) as evidence_count,
       (array_agg(evidence_ref))[1] as example_ref,
       -- a handle claimed by many businesses is a theme vendor / agency / platform, not the business
       count(*) over (partition by platform, handle) as businesses_claiming
from u where handle ~ '^[a-z0-9_.\-]{2,60}$'
group by 1, 2, 3
