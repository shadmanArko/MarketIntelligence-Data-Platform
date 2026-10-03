-- berlin.de festivals and Christmas markets; one row per event and observation (announcements change).
select o.observation_id, o.fetched_at, o.natural_key as feed, (e.value ->> 'id') as event_id,
  {{ clean_text("e.value ->> 'bezeichnung'") }} as name, e.value ->> 'bezirk' as district,
  {{ clean_text("e.value ->> 'strasse'") }} as address, e.value ->> 'plz' as postcode,
  to_date(e.value ->> 'von', 'DD.MM.YYYY') as starts_on, to_date(e.value ->> 'bis', 'DD.MM.YYYY') as ends_on,
  {{ clean_text("e.value ->> 'zeit'") }} as opening_times, {{ clean_text("e.value ->> 'veranstalter'") }} as organiser,
  {{ clean_url("e.value ->> 'www'") }} as website, {{ clean_text("e.value ->> 'bemerkungen'") }} as description
from {{ raw_entity('berlin_events', 'feed') }} o, jsonb_array_elements(ops.jarr(o.payload -> 'index')) e
where e.value ->> 'von' ~ '^\d{2}\.\d{2}\.\d{4}$'
