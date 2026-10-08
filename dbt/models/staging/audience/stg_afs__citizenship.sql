-- Foreign residents of Berlin by citizenship (A I 5, T10): total, female and 4 age groups, per half-year release.
-- The sheet interleaves leaf rows (one citizenship) with subtotals: per region / EU / Nicht-EU ("Zusammen"), per
-- continent ("Afrika zusammen") and the grand total ("Insgesamt"). is_aggregate marks the subtotals; sum residents
-- only where not is_aggregate. Layout differs by release (2025h2 has sub-regions, 2026h1 only continents), and the
-- loader's section path is "<continent> / <region>" (2025h2) or "Europa / <continent>" (2026h1, stale first level).
-- Scope also differs: in 2025h2 "China" includes Hongkong, Macau and Taiwan and "Serbien" includes the former
-- "Serbien und Montenegro" / "Serbien (einschließlich Kosovo)"; 2026h1 lists those separately.
with c as (
  select reference_date, row_no, column_label, value,
         split_part(section, ' / ', 1) as s1, split_part(section, ' / ', 2) as s2,
         -- residual categories ("Staatenlos") sit in key1 with an empty key2 in older releases; key1 is
         -- forward-filled by the loader, so key2 wins whenever present
         coalesce(key2, key1) as label
  from {{ dataset_table('afs_population') }}
  where sheet = 'T10 G1' and coalesce(key2, key1) is not null and section not like '%Daten für Grafik%'
),
r as (
  select distinct on (reference_date, row_no) reference_date, row_no, s1, s2,
    -- footnote markers glued to labels: "China7", "Sonstiges Asien⁵, ⁶", "Ungeklärte Staatsangehörigkeit ⁶"
    replace(replace(replace(btrim(regexp_replace(label, '[0-9⁰¹²³⁴⁵⁶⁷⁸⁹, ]+$', '')),
      'Aurprägungen', 'Ausprägungen'), '/zeanien/', '/Ozeanien/'), '’', '''') as label,  -- source typos
    label as source_label,
    nullif(btrim(regexp_replace(s2, '[0-9⁰¹²³⁴⁵⁶⁷⁸⁹, ]+$', '')), '') as section_label
  from c
),
g as (
  select r.*,
    case when section_label in ('Europäische Union (EU)', 'Nicht-EU-Länder') then 'Europa'
         when section_label in ('Afrika', 'Amerika', 'Asien', 'Australien/Ozeanien/Antarktis', 'Sonstige Ausprägungen')
           then section_label
         else nullif(s1, '') end as continent,
    case when section_label in ('Afrika', 'Amerika', 'Asien', 'Australien/Ozeanien/Antarktis', 'Sonstige Ausprägungen')
           then null
         else section_label end as region,
    -- member rows of the section, i.e. not counting the subtotals that close it
    count(*) filter (where label !~* '(^|\s)(zusammen|insgesamt)$') over (partition by reference_date, s1, s2)
      as section_members
  from r
),
k as (
  select g.reference_date, g.row_no, g.source_label,
    case
      when g.label = 'Insgesamt' then null
      when g.label ~* '^(.+) zusammen$' then substring(g.label from '^(.+) zusammen$')   -- "Europa zusammen"
      else g.continent end as continent,
    case when g.label ~* '(^|\s)(zusammen|insgesamt)$' and g.label !~* '^zusammen$' then null else g.region end
      as region,
    case
      -- a bare "Zusammen" is the subtotal of its section ...
      when g.label ~* '^zusammen$' and g.section_members > 0 then coalesce(g.region, g.continent) || ' zusammen'
      -- ... unless the section has no member rows ("Sonstiges Afrika" in 2025h2): then it is the category itself
      when g.label ~* '^zusammen$' then coalesce(g.region, g.continent)
      -- labels renamed between releases -> one spelling (the 2026h1 one, which communities.yaml uses)
      else coalesce(a.citizenship, g.label) end as citizenship
  from g left join {{ ref('afs_citizenship_alias') }} a on a.source_label = g.label
),
l as (
  select k.*, citizenship ~* '(^|\s)(zusammen|insgesamt)$' as is_aggregate from k
)
select l.reference_date, l.citizenship, l.continent, l.region, l.is_aggregate, l.source_label,
  max(c.value) filter (where c.column_label = 'Insgesamt / insgesamt')::int as residents,
  max(c.value) filter (where c.column_label = 'Darunter weiblich / zusammen')::int as female,
  max(c.value) filter (where c.column_label like 'Insgesamt / % / unter 15')::int as age_under_15,
  max(c.value) filter (where c.column_label like 'Insgesamt / % / 15 - 45')::int as age_15_45,
  max(c.value) filter (where c.column_label like 'Insgesamt / % / 45 - 65')::int as age_45_65,
  max(c.value) filter (where c.column_label like 'Insgesamt / % / 65 und mehr')::int as age_65_plus
from l join c using (reference_date, row_no)
group by l.reference_date, l.row_no, l.citizenship, l.continent, l.region, l.is_aggregate, l.source_label
