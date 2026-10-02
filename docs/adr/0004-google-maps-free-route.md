# ADR 0004 — Google Maps via template replay, paced

**Decision.** A headless browser opens Google Maps once to capture a valid search request template; every grid
cell × term × page is then a plain HTTP request. The sweep starts at H3 res 7 and subdivides cells that are
still full after 10 pages. Pacing is one request every ~3 s; on HTTP 429 the platform backs off and resumes
later rather than evading the limit.

**Why.** The Places API's ratings/reviews tiers are paid per call; the web route gives the same fields for
free. Google throttles an IP after a few thousand fast searches, so slow and steady finishes the city.
