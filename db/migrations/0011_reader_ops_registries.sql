-- The reader also needs the lineage registries and enrichment outputs that core / ml join to (no queue, no secrets).
GRANT USAGE ON SCHEMA ops TO mip_reader;
GRANT SELECT ON ops.datasets, ops.text_language, ops.content_tag, ops.business_assignment, ops.brand_assignment,
                ops.social_assignment, ops.quality_report, ops.runs TO mip_reader;
