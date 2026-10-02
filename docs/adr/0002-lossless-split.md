# ADR 0002 — Lossless split of list responses

**Decision.** City-wide list responses (Wolt grid points, Lieferando postcodes, Google Maps search pages) are
split into (a) a `coverage` / `search_page` record holding the envelope and every location-dependent field per
item, and (b) one record per entity with those fields moved out. Together they reconstruct the original.

**Why.** Without the split, 1,351 grid points × ~2,000 venues would store ~5 GB of near-duplicate JSON per sweep;
with it the stable venue body is content-addressed once and per-point fees / estimates / ranks stay exact.
