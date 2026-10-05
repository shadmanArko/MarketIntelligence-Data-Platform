-- TikTok audio watchlist: which sounds Berlin food accounts used in the last 12 months and how those videos did
-- against each account's own median. original_sound = the creator's own audio (voice, sizzle, kitchen).
-- Business accounts may only use TikTok's Commercial Music Library: check a track is there before using it.
with cp as (
  select *, case when audio_title is null then 'none'
                 when audio_title ~* '(original|originalton|orijinal|оригинальн|оригінальн|الصوت الأصلي|origineel)' then 'original_sound'
                 else 'named_track' end as audio_kind
  from {{ ref('content_performance') }}
  where platform = 'tiktok' and mature and perf_lift_vs_peer is not null and posted_at > now() - interval '365 days'
)
select audio_kind, case when audio_kind = 'named_track' then audio_title end as audio_title,
       count(*) as videos, count(distinct peer_group) as accounts,
       avg(perf_lift_vs_peer) as mean_lift, avg(is_viral_in_peer::int) as viral_share,
       max(posted_at) as last_used_at,
       count(*) filter (where posted_at > now() - interval '60 days') as videos_last_60d
from cp
group by 1, 2
having count(distinct peer_group) >= 5
