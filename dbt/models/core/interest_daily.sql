{{ config(indexes=[{'columns': ['topic', 'day']}]) }}
-- Public interest per topic (dish, cuisine, occasion) per day, summed over language editions and per language.
select topic, day, sum(views) as views_all_languages,
       sum(views) filter (where lang = 'de') as views_de, sum(views) filter (where lang = 'en') as views_en,
       sum(views) filter (where lang in ('bn', 'ur', 'hi')) as views_south_asian_langs,
       sum(views) filter (where lang in ('ar', 'tr')) as views_ar_tr
from {{ ref('stg_wikipedia__pageviews') }} group by 1, 2
