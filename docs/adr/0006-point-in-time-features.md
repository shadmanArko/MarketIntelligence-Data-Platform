# ADR 0006 — Point-in-time features and versioned training sets

**Decision.** `ml.feature_*` models take `var('as_of')` and only read snapshots observed at or before it.
`mip ml export` builds the model for a cut-off, writes Parquet (one folder per version) with a manifest, the
compiled SQL and the dataset versions in force, and registers it in `ml.training_sets`. Splits are by time
(train on earlier cut-offs) and grouped by business. Missing values stay NULL with `*_missing` indicators.
