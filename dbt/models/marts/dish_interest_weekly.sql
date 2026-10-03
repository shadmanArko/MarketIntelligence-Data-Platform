-- Weekly public interest per dish / cuisine / occasion, with the share of each week in that topic's year.
select topic, date_trunc('week', day)::date as week, sum(views_all_languages) as views,
       sum(views_de) as views_de, sum(views_south_asian_langs) as views_south_asian_langs
from {{ ref('interest_daily') }} group by 1, 2
