{{ config(indexes=[{'columns': ['url_canonical', 'valid_from']}]) }}
-- One version of one page: a new row only when the content hash changes (unchanged pages collapse).
with p as (
  select *, lag(content_sha256) over (partition by url_canonical order by fetched_at) as prev_hash
  from {{ ref('stg_web__page') }} where status between 200 and 299 and main_text is not null
)
select md5(url_canonical || ':' || encode(content_sha256, 'hex'))::uuid as page_version_id,
       url_canonical, final_url, domain, site_kind, seed_business_id, title, meta_description, main_text,
       main_text_length, lang_attr, jsonld, opengraph, social_links, ordering_providers, emails, phones,
       fetched_at as valid_from, content_sha256
from p where prev_hash is distinct from content_sha256
