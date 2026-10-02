-- Point-in-time menu-item features (dish classification / price models): text kept raw beside the label.
{% set as_of = var('as_of', none) %}
{% set as_of_sql = "'" ~ as_of ~ "'::timestamptz" if as_of else "now()" %}
select o.offering_id, a.business_id, o.platform, {{ as_of_sql }} as as_of,
       o.name, o.description, o.category, o.dish_id, o.image_url,
       (o.attributes ->> 'halal')::boolean as is_halal, (o.attributes ->> 'vegan')::boolean as is_vegan,
       (o.attributes ->> 'vegetarian')::boolean as is_vegetarian, (o.attributes ->> 'spicy')::boolean as is_spicy,
       (o.attributes ->> 'drink')::boolean as is_drink, (o.attributes ->> 'alcohol')::boolean as has_alcohol,
       o.option_group_count, jsonb_array_length(ops.jarr(o.size_variants)) as size_variant_count,
       p.price, p.original_price, p.discount_share, mpi.price_index, mpi.berlin_median_price
from {{ ref('offering') }} o
join {{ ref('listing') }} l using (listing_id)
join ops.business_assignment a on a.listing_key = l.listing_key
join lateral (select price, original_price, discount_share from {{ ref('offering_price_snapshot') }} ps
              where ps.offering_id = o.offering_id and ps.observed_at <= {{ as_of_sql }} and ps.outlier_reason is null
              order by ps.observed_at desc limit 1) p on true
left join {{ ref('menu_price_index') }} mpi using (offering_id)
where o.first_seen_at <= {{ as_of_sql }} and l.in_market
