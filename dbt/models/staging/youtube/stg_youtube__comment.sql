-- Top-level comments (by relevance) on tier-1 videos; authors are salted hashes. Used for audience language mix.
select o.observation_id, o.fetched_at, o.payload ->> 'video_id' as video_id,
       x.value ->> 'id' as comment_id, {{ clean_text("x.value ->> 'text'") }} as text,
       (x.value ->> 'likes')::bigint as likes, (x.value ->> 'replies')::int as replies,
       (x.value ->> 'published_at')::timestamptz as published_at, x.value ->> 'author' as author_hash
from {{ raw_entity('youtube', 'comments') }} o, jsonb_array_elements(ops.jarr(o.payload -> 'items')) x
