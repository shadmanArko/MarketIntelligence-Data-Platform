-- Per canonical dish: how many Berlin businesses sell it, at what prices, on which platforms.
select dish_id, count(distinct business_id) as businesses, count(*) as offerings,
       min(berlin_median_price) as median_price, min(berlin_p25) as p25, min(berlin_p75) as p75,
       count(distinct business_id) filter (where platform = 'wolt') as on_wolt,
       count(distinct business_id) filter (where platform = 'lieferando') as on_lieferando
from {{ ref('menu_price_index') }} group by 1
