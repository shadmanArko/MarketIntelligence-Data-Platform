-- Platforms that do not report a metric must have NULL, never 0 (missing is not zero).
select * from {{ ref('tenant_social_metrics_snapshot') }}
where (platform = 'instagram' and impressions is not null)
   or (platform = 'threads' and reach is not null)
   or (platform <> 'facebook' and clicks is not null)
