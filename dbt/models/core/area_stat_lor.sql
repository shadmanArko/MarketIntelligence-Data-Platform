{{ config(materialized='table', indexes=[{'columns': ['area_id', 'variable']}]) }}
-- Zensus 2022 100 m cells aggregated to Berlin LOR planning areas (same rules as area_stat: sums / weighted means).
{%- set rows = [] -%}
{%- if execute -%}
  {%- set rows = run_query("select name, raw_table, meta from ops.datasets where name like 'zensus2022_%' order by name").rows -%}
{%- endif %}
with pop as (select grid_id, einwohner::float8 as pop, lat, lon from raw."ds_zensus2022_population"),
plr as (
  select z.grid_id, a.code from pop z
  join raw.geo_area a on a.kind = 'planning_area' and st_covers(a.geom, st_setsrid(st_makepoint(z.lon, z.lat), 4326))
),
v as (
{%- for r in rows %}
  {%- set tbl = r[1].split('.')[1] %}
  {%- set cols = fromjson(r[2])['value_columns'] if r[2] is string else r[2]['value_columns'] %}
  {%- for c in cols if not c.startswith('werterlaeuternde') %}
    {%- set is_rate = c.startswith('anteil') or c.startswith('durchschn') or c.endswith('quote') or c.startswith('auslaenderanteil') %}
  select '{{ r[0] | replace("zensus2022_", "") }}.{{ c }}' as variable, plr.code,
         {% if is_rate %}'weighted_mean'{% else %}'sum'{% endif %} as agg, z."{{ c }}"::float8 as value, coalesce(p.pop, 0) as weight
  from raw."{{ tbl }}" z join plr using (grid_id) left join pop p using (grid_id) where z."{{ c }}" is not null
  {% if not loop.last %}union all{% endif %}
  {%- endfor %}
  {% if not loop.last %}union all{% endif %}
{%- endfor %}
)
select 'lor_planning_area' as area_type, code as area_id, variable,
       case when agg = 'sum' then sum(value) else sum(value * weight) / nullif(sum(weight), 0) end as value,
       agg as aggregation, count(*) as source_cells, date '2022-05-15' as reference_date, 'zensus2022' as source_dataset
from v group by code, variable, agg
