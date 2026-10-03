-- Every Berlin restaurant on TripAdvisor in May 2021: is the business still seen today, and how did its rating move?
with ta as (
  select a.business_id, l.listing_id, l.name as name_2021
  from {{ ref('listing') }} l join ops.business_assignment a using (listing_key)
  where l.platform = 'tripadvisor'
),
ta_rating as (
  select s.listing_id, s.rating_value as rating_2021, s.rating_count as reviews_2021
  from {{ ref('listing_snapshot') }} s where s.platform = 'tripadvisor'
)
select t.business_id, t.name_2021, b.name as name_now, b.primary_cuisine, b.district,
       r.rating_2021, r.reviews_2021,
       c.google_rating as google_rating_now, c.google_review_count as google_reviews_now,
       round((c.google_rating - r.rating_2021)::numeric, 2) as rating_change_vs_google,
       b.listing_count > 1 as seen_on_other_sources,
       b.delivery_platform_count > 0 as on_delivery_apps_now,
       case when b.status = 'closed' then 'closed'
            when b.listing_count > 1 and b.status = 'active' then 'surviving'
            when b.listing_count = 1 then 'not_seen_since_2021'
            else b.status end as survival_status
from ta t
join {{ ref('business') }} b using (business_id)
left join ta_rating r using (listing_id)
left join {{ ref('competitor_overview') }} c using (business_id)
