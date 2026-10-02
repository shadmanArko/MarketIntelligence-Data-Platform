# ADR 0003 — Entity resolution: Splink scores, constrained clustering decides

**Decision.** Deterministic links (phone / domain / legal id / address with name agreement, < 150 m) plus a
Splink Fellegi–Sunter model (EM, no labels; name m-probabilities fixed). Clustering is union-find over edges
≥ 0.9 that need name agreement or ≥ 5 shared menu items, under cannot-link constraints: one listing per
exclusive platform (Wolt, Lieferando, Google Maps) per business, ≤ 400 m span, no conflicting street addresses,
complete-linkage name similarity with rare-token weighting. Phones / domains shared by > 2 different names are
not evidence. Stable ids live in `ops.business_assignment`; merges / splits / moves go to `ops.entity_changes`.

**Why.** Unsupervised EM on location blocks learns "same building = same business" (malls, food halls) and
connected components chain chain-branches together; the constraints remove both failure modes. Gate 2 is
measured on human labels (`mip resolve review` / `evaluate`), precision ≥ 0.95.
