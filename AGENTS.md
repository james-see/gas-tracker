# gas-tracker — repo conventions

## Stack
- Python 3.12 in CI; scraper deps: curl_cffi only. pytest for tests.
- Frontend: single index.html, inline CSS/JS, NO build step, NO npm.
- Data: plain JSON in data/ committed by Actions (latest.json, history/, ondemand/).

## Data model
- Locations have {key, search, label}: Arlington = 5-digit zip keys, metros =
  slugified city keys (e.g. pittsburgh-pa) with "City, ST" search strings.
- Zip-level search can return 0 stations for downtown zips (15222) — metros
  MUST use city search. Arlington uses zip search for neighborhood stations.
- GasBuddy GraphQL requires: GET /home first (curl_cffi impersonate="chrome")
  → window.gbcsrf token → POST /graphql with gbcsrf header AND
  apollo-require-preflight: true (missing this = 400 Bad Request).
- credit.price == 0 means no report ("- - -"); filter these out.
- stationCount mirrors the API area count (includes unpriced stations).

## Rate limits
- ~15 rapid /graphql calls trigger 429. Scraper paces 2.5-5s jitter,
  exponential backoff on 429 (client), aborts after 5 consecutive 429s.
- Partial runs (--only) pass partial=True to merge_latest so unattempted
  locations are NOT stale-flagged.

## Testing
- pytest with tests/fixtures/location_22207.json (real recorded response).
- Never add tests that hit the network; live checks are CI-only, non-blocking.

## Workflows
- update-prices: hourly cron + ET-hour gate (07/17) + dispatch; commits data/.
- ondemand: workflow_dispatch zip input, validated ^[0-9]{5}$.
- deploy-pages: build_type=workflow (actions/deploy-pages@v4), paths-filtered.
- gh token needs `workflow` scope to push .github/workflows changes.

## Style
- No ORM, plain dicts. Atomic JSON writes (tmp + os.replace).
- Mobile-first, WCAG-ish: 44px tap targets, aria-pressed on chips, labels on inputs.
- Attribution to GasBuddy contributors in README + page footer. Unofficial API
  disclaimer required.