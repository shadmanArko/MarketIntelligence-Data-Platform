# ADR 0005 — Politeness and hard boundaries

**Decision.** Per-source and per-host token buckets with adaptive slow-down on 429, circuit breakers, robots.txt
honoured by the web crawler (configurable), no CAPTCHA solving or bot-challenge evasion, reviewer / commenter
identities salted-hashed before raw. Where a source answers with a challenge (DuckDuckGo HTML, Google organic)
or the permission layer blocks an approach (Uber Eats internal API), the platform uses an official API slot
instead and lists it in docs/paid-sources.md.
