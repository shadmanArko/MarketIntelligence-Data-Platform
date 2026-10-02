{{ config(materialized='table', indexes=[{'columns': ['area_id', 'variable']}]) }}
-- Area x variable x reference date. Zensus 2022 100 m cells aggregated to H3 res 8:
-- counts are summed, shares / means / rates are population-weighted. Long format, one row per value.
{%- set rows = [] -%}
{%- if execute -%}
  {%- set res = run_query("select name, raw_table, meta from ops.datasets where name like 'zensus2022_%' order by name") -%}
  {%- set rows = res.rows -%}
{%- endif %}
with pop as (
  select grid_id, einwohner::float8 as pop, lat, lon,
         h3_lat_lng_to_cell(point(lon, lat), 8)::text as cell
  from raw."ds_zensus2022_population"
),
cells as (select cell from raw.geo_h3 where res = 8 and in_market),
v as (
{%- for r in rows %}
  {%- set name = r[0] %}
  {%- set tbl = r[1].split('.')[1] %}
  {%- set cols = fromjson(r[2])['value_columns'] if r[2] is string else r[2]['value_columns'] %}
  {%- for c in cols if not c.startswith('werterlaeuternde') %}
    {%- set is_rate = c.startswith('anteil') or c.startswith('durchschn') or c.endswith('quote') or c.startswith('auslaenderanteil') %}
  select '{{ name | replace("zensus2022_", "") }}.{{ c }}' as variable, h3_lat_lng_to_cell(point(z.lon, z.lat), 8)::text as cell,
         {% if is_rate %}'weighted_mean'{% else %}'sum'{% endif %} as agg,
         z."{{ c }}"::float8 as value, coalesce(p.pop, 0) as weight
  from raw."{{ tbl }}" z left join pop p using (grid_id)
  where z."{{ c }}" is not null
  {% if not loop.last %}union all{% endif %}
  {%- endfor %}
  {% if not loop.last %}union all{% endif %}
{%- endfor %}
{%- if rows | length == 0 %}
  select null::text as variable, null::text as cell, null::text as agg, null::float8 as value, null::float8 as weight where false
{%- endif %}
)
select
  'h3_r8'                                                  as area_type,
  v.cell                                                   as area_id,
  v.variable,
  case when v.agg = 'sum' then sum(v.value)
       else sum(v.value * v.weight) / nullif(sum(v.weight) filter (where v.value is not null), 0) end as value,
  v.agg                                                    as aggregation,
  count(*)                                                 as source_cells,
  date '2022-05-15'                                        as reference_date,   -- Zensus 2022 key date
  'zensus2022'                                             as source_dataset
from v join cells c on c.cell = v.cell
group by v.cell, v.variable, v.agg
