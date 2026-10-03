{{ config(indexes=[{'columns': ['post_id']}, {'columns': ['tag_type', 'tag_id']}]) }}
-- Dishes, communities, occasions and format cues per post (from `mip enrich content`, dictionary matcher).
select t.text_id::uuid as post_id, t.tag_type, t.tag_id, t.matched, t.matcher, t.tagged_at
from ops.content_tag t
where t.text_kind = 'post'
  and exists (select 1 from {{ ref('post') }} p where p.post_id = t.text_id::uuid)
