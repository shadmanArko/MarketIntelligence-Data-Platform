-- One row per crawled page observation (restaurant sites and food media).
with src as {{ raw_entity('web_crawl', 'web_page', ok_only=false) }}
select
  observation_id, run_id, fetched_at, payload_sha256 as content_sha256,
  natural_key                                              as url_canonical,
  payload ->> 'url'                                        as url,
  payload ->> 'final_url'                                  as final_url,
  (payload ->> 'status')::integer                          as status,
  http_status,
  payload ->> 'kind'                                       as site_kind,           -- business | media
  payload ->> 'site'                                       as site,
  {{ registrable_domain("payload ->> 'final_url'") }}      as domain,
  (payload ->> 'business_id')::uuid                        as seed_business_id,
  (payload ->> 'depth')::integer                           as depth,
  (payload ->> 'blocked_by_robots')::boolean               as blocked_by_robots,
  payload ->> 'error'                                      as error,
  {{ clean_text("payload #>> '{meta,title}'") }}           as title,
  {{ clean_text("payload #>> '{meta,description}'") }}     as meta_description,
  payload #>> '{meta,sitename}'                            as sitename,
  (payload #>> '{meta,date}')                              as page_date,
  {{ clean_text("payload ->> 'main_text'") }}              as main_text,
  length(payload ->> 'main_text')                          as main_text_length,
  coalesce(payload ->> 'lang_attr', payload #>> '{meta,language}') as lang_attr,
  payload #> '{structured,json-ld}'                        as jsonld,
  payload #> '{structured,opengraph}'                      as opengraph,
  payload -> 'social_links'                                as social_links,
  ops.jarr(payload -> 'ordering_providers')                as ordering_providers,
  ops.jarr(payload -> 'emails')                            as emails,
  ops.jarr(payload -> 'phones')                            as phones,
  jsonb_array_length(ops.jarr(payload -> 'outgoing_links')) as outgoing_link_count,
  payload -> 'headers'                                     as headers
from src
