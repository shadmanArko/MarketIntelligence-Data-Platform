{{ config(severity='warn') }}
-- Every afs_citizenship label in communities.yaml must name a citizenship in the latest AfS T10 release; a miss means
-- the source renamed it (map the old spelling in seeds/afs_citizenship_alias.csv, update communities.yaml).
-- "Deutschland" never matches: T10 counts foreign citizens only.
with lab as (
  select community_id, unnest(string_to_array(nullif(afs_citizenship, ''), '|')) as citizenship
  from {{ ref('community') }}
),
cur as (
  select citizenship from {{ ref('stg_afs__citizenship') }}
  where not is_aggregate and reference_date = (select max(reference_date) from {{ ref('stg_afs__citizenship') }})
)
select lab.community_id, lab.citizenship from lab
where lab.citizenship <> 'Deutschland' and lab.citizenship not in (select citizenship from cur)
