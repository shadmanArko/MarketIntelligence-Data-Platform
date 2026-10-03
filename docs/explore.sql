-- Starter queries for exploring the Market Intelligence database (DataGrip / psql).
-- Schemas: raw (as received) -> staging (cleaned views) -> core (resolved entities) -> marts (analysis) -> ml (features)
-- ops = runs, task queue, quality checks, dataset registry.

-- 1. What is in the database: row counts of the main tables
select 'core.business' as tbl, count(*) from core.business union all
select 'core.listing', count(*) from core.listing union all
select 'core.offering (menu items)', count(*) from core.offering union all
select 'core.review', count(*) from core.review union all
select 'core.web_page', count(*) from core.web_page union all
select 'core.post', count(*) from core.post union all
select 'marts.competitor_overview', count(*) from marts.competitor_overview;

-- 2. Businesses per platform combination (how restaurants are spread across Wolt, Lieferando, Google, maps data)
select on_wolt, on_lieferando, on_google_maps, count(*) as businesses
from core.business where in_market
group by 1, 2, 3 order by 4 desc;

-- 3. Cuisines in Berlin, with how many deliver
select primary_cuisine, count(*) as businesses, count(*) filter (where delivery_platform_count > 0) as delivering
from core.business where in_market and status <> 'closed'
group by 1 order by 2 desc limit 30;

-- 4. Every South Asian competitor with ratings, fees and menu size
select name, primary_cuisine, district, google_rating, google_review_count, wolt_rating, lieferando_rating,
       min_order_minimum, min_base_delivery_fee, menu_items, median_item_price, website
from marts.competitor_overview
where primary_cuisine_group = 'south_asian'
order by rating_count_total desc nulls last;

-- 5. Biryani market: who sells which biryani and at what price vs the Berlin median
select b.name, m.platform, m.name as item, m.dish_id, m.price, m.berlin_median_price, m.price_index
from marts.menu_price_index m join core.business b using (business_id)
where m.dish_id like '%biryani%'
order by m.dish_id, m.price;

-- 6. Price overview per canonical dish
select * from marts.dish_market order by businesses desc;

-- 7. One business seen across all platforms (change the name)
select l.platform, l.name, l.address_line, l.phone, l.website, l.legal_name, l.vat_number
from core.business b
join ops.business_assignment a using (business_id)
join core.listing l using (listing_key)
where b.name ilike '%al reef%';

-- 8. Full menu of one restaurant (change the name)
select o.platform, o.category, o.name, o.description, p.price, o.dish_id, o.attributes
from core.offering o
join core.listing l using (listing_id)
join lateral (select price from core.offering_price_snapshot s where s.offering_id = o.offering_id
              order by observed_at desc limit 1) p on true
where l.name ilike '%safran%'
order by o.platform, o.category, o.position;

-- 9. Latest reviews with text (Lieferando; reviewer is a hash, never a name)
select b.name, r.posted_at, r.rating_value, r.text, r.owner_reply
from core.review r
join core.listing l using (listing_id)
join ops.business_assignment a on a.listing_key = l.listing_key
join core.business b using (business_id)
where r.text is not null
order by r.posted_at desc limit 50;

-- 10. Where demand may be under-served: population vs South Asian venues delivering, per H3 cell
select h3_r8, round(lat::numeric, 4) lat, round(lon::numeric, 4) lon, population, foreigner_share_pct,
       south_asian_venues_delivering, residents_per_south_asian_venue
from marts.area_demand
where population > 3000
order by residents_per_south_asian_venue desc nulls first limit 30;

-- 11. Districts: businesses, delivery share, average Google rating
select district, count(*) as businesses,
       round(avg((delivery_platform_count > 0)::int) * 100) as pct_delivering,
       round(avg(google_rating), 2) as avg_google_rating
from marts.competitor_overview group by 1 order by 2 desc;

-- 12. Who is most visible on Google Maps for each search term
select query, b.name, round(share_of_search::numeric, 4) as share_of_search, best_rank, cells_visible
from marts.search_visibility s join core.business b using (business_id)
order by query, share_of_search desc;

-- 13. Keyword rankings ("biryani berlin" etc.), map results per district
select p.payload ->> 'keyword' as keyword, p.payload ->> 'area' as area,
       r ->> 'rank' as rank, r ->> 'name' as business, r ->> 'rating' as rating, r ->> 'reviews' as reviews
from raw.observations o join raw.payloads p using (payload_sha256),
     jsonb_array_elements(p.payload -> 'results') r
where o.source = 'serp' and p.payload ->> 'keyword' = 'biryani berlin' and p.payload ->> 'area' = 'berlin'
order by (r ->> 'rank')::int;

-- 14. Chains: biggest brands in Berlin
select brand_name, locations from core.brand order by locations desc limit 30;

-- 15. Social accounts found on restaurant websites (after `mip resolve social`)
select split_part(s.account_key, ':', 1) as platform, split_part(s.account_key, ':', 2) as handle,
       b.name, round(s.score::numeric, 2) as score, s.decision
from ops.social_assignment s left join core.business b using (business_id)
where s.decision in ('auto', 'review') order by s.score desc limit 50;

-- 16. TikTok videos with the most views
select handle, views, likes, comments, shares, saves, duration_s, left(caption, 80) as caption, permalink
from staging.stg_tiktok__video where views is not null order by views desc limit 30;

-- 17. Census around a point: everything known about one H3 cell (change the cell id from query 10)
select variable, round(value::numeric, 2) value, aggregation
from core.area_stat where area_id = (select h3_r8 from marts.area_demand order by population desc nulls last limit 1)
order by variable;

-- 18. Raw JSON exactly as received from a platform (one Wolt venue page)
select o.fetched_at, o.http_status, jsonb_pretty(p.payload) as payload
from raw.observations o join raw.payloads p using (payload_sha256)
where o.source = 'wolt' and o.entity_type = 'venue_static' limit 1;

-- 19. Collection health: runs, failures, quality checks
select source, command, status, started_at, ended_at, metrics -> 'tasks' as tasks from ops.runs order by started_at desc limit 20;
select source, entity_type, metric, value, previous, passed, created_at from ops.quality_report
where not passed order by created_at desc limit 20;

-- 20. Registered datasets and ML training sets
select name, version, row_count, terms, loaded_at from ops.datasets order by name;
select name, version, as_of, row_count, path from ml.training_sets order by name, version;
