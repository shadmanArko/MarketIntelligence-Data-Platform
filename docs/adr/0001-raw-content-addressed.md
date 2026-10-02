# ADR 0001 — Raw is content-addressed and immutable

**Decision.** Every response lands in `raw.payloads` keyed by SHA-256 of its canonical JSON, plus one
`raw.observations` row per fetch (lineage: run, task, connector version, request, status, time). Nothing in raw
is ever updated or deleted; everything after raw is rebuilt by dbt.

**Why.** Refreshes cost almost no disk (identical responses are stored once) while every observation is still
recorded; a field ignored today can be promoted next year without re-scraping.
