{{ config(indexes=[{'columns': ['business_id']}]) }}
-- A business mentioned on a food-media / guide page (matching done by `mip enrich mentions`).
select md5(m.page_version_id::text || m.business_id::text)::uuid as mention_id,
       m.page_version_id, p.url_canonical, p.domain, m.business_id, m.matched_name, m.snippet,
       null::numeric as sentiment,     -- left NULL: no sentiment model in this platform's scope
       p.valid_from as observed_at, m.matcher
from ops.text_mention m join {{ ref('web_page') }} p using (page_version_id)
