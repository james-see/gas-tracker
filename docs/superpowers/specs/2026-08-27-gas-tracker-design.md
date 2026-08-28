# Gas Price Tracker — Design

**Date:** 2026-08-27
**Repo:** `github.com/james-see/gas-tracker` (local `~/p/gas-tracker`)
**Status:** Approved by James (name: gas-tracker; Pittsburgh added to metros)

## Problem

Show average and lowest regular gas prices for Arlington-area zipcodes plus major
US metros, on a fast mobile-first page, with price history. No server, no API keys.

## Solution

GitHub Actions runs a Python scraper twice daily (7am & 5pm ET), which commits
normalized JSON into the repo; GitHub Pages serves a zero-build static page that
reads the JSON. Users can fetch an arbitrary zipcode on demand via a
workflow_dispatch call from the page (their own fine-grained PAT, stored in their
browser's localStorage — never in the repo).

## Data source

GasBuddy's unofficial GraphQL API (`https://www.gasbuddy.com/graphql`), the same
endpoint used by py-gasbuddy / Home Assistant. Flow, verified live 2026-08-27:

1. `GET /home` with Chrome TLS impersonation (`curl_cffi`) → passes Cloudflare →
   extract CSRF token from `window.gbcsrf = "..."`.
2. `POST /graphql` with header `gbcsrf: <token>` → `LocationBySearchTerm` query
   (fuel=1 regular, maxAge=3) → `trends[0] {areaName, today, todayLow}` +
   `stations.results[{name, address, prices[]}]`.

Attribution: "Data from GasBuddy community contributors." Unofficial-API
disclaimer in README and page footer.

## Components

### scraper_lib.py (pure-ish library)
- `GasBuddyClient`: curl_cffi session (impersonate chrome), `get_csrf()`,
  `location_search(zip) -> dict` with 3 retries (fresh CSRF on 401/403).
- `parse_location(raw, zip) -> dict`: normalized zip entry (shape below).
- `merge_latest(old, new, ok_zips)`: keeps previous entry (flagged `stale`) for
  zips that failed this run.
- `append_history(points, entry, now, max_days=30)`: rolling window.

### Zip entry shape (latest.json)
```json
{
  "generated": "2026-08-27T19:05:00Z",
  "zips": {
    "22207": {
      "zip": "22207", "areaName": "Virginia", "avg": 3.88, "low": 3.35,
      "stationCount": 9, "stale": false, "lastUpdated": "2026-08-27T19:05:00Z",
      "stations": [{"name": "BP", "address": "5601 Lee Highway, Arlington, VA",
                     "price": 3.85, "updated": "2026-08-27T16:12:00Z"}]
    }
  }
}
```
`stations` = 10 cheapest with a regular price (credit price). `history/<zip>.json`
= `{"zip": "...", "points": [{"t", "avg", "low"}]}` rolling 30 days.
`ondemand/<zip>.json` = same entry shape, written by the ondemand workflow.

### scraper.py (CLI)
`python scraper.py --zips 22207,15222 --out-dir data [--print] [--single 15222]`
- One CSRF per run, reused across zips; refreshed on auth errors.
- 1–3s jitter between zips; per-zip failure is isolated and logged.
- Merges into existing latest.json + history files, writes atomically.
- Exit 1 only if every zip failed.

### Data files (committed by Actions to `main`)
- `data/latest.json` — all tracked zips, current snapshot
- `data/history/<zip>.json` — per-zip 30-day rolling history
- `data/ondemand/<zip>.json` — user-triggered lookups

### Workflows (.github/workflows/)
- `update-prices.yml` — hourly cron with ET-hour gate (run only at 7am/5pm
  America/New_York, or on workflow_dispatch). Concurrency-guarded. Commits data.
- `ondemand.yml` — workflow_dispatch with `zip` input (validated `^[0-9]{5}$`),
  scrapes one zip, writes ondemand + history, commits.
- `ci.yml` — pytest on push/PR; separate non-blocking live-smoke step (one zip).
- `deploy-pages.yml` — push to main (index/data paths) or manual → upload-pages
  artifact + actions/deploy-pages. Pages source set to "GitHub Actions"
  (`build_type=workflow`) per verified-reliable pattern.

### index.html (single file, inline CSS+JS, no build, no deps)
Mobile-first single column (max ~680px), `prefers-color-scheme` dark mode,
viewport + theme-color meta, ≥44px tap targets. Sections:

1. **Arlington card (default, 22207)** — big avg, low, state name, 30-day
   sparkline (hand-rolled inline SVG, no chart lib), "30-day low $X on DATE"
   callout, week-over-week delta.
2. **Cheapest stations** — top 10 for selected zip: brand, address, price,
   report age.
3. **Metros: bottom 10 cheapest / top 10 priciest** across all tracked zips.
4. **All metros** — compact grid (avg, low, trend arrow vs last history point).
5. **On-demand zip** — input; with PAT (localStorage) calls `workflow_dispatch`
   then polls `data/ondemand/<zip>.json` every 10s ≤4min; without PAT falls back
   to a "search on GasBuddy" link.

### Zip list (scraper ZIPS constant)
Arlington (default): 22207, 22201, 22204, 22202.
Metros: 10001 NYC, 90001 LA, 60601 Chicago, 77002 Houston, 85001 Phoenix,
19103 Philadelphia, 78205 San Antonio, 92101 San Diego, 75201 Dallas, 95113
San Jose, 78701 Austin, 32202 Jacksonville, 43215 Columbus, 98101 Seattle,
80202 Denver, 02108 Boston, 37203 Nashville, 30303 Atlanta, 33130 Miami,
48226 Detroit, 55401 Minneapolis, **15222 Pittsburgh**, 63101 St. Louis,
33602 Tampa, 97204 Portland, 89101 Las Vegas, 20001 Washington DC.

## Error handling
- Retries with backoff + fresh CSRF; per-zip isolation; stale-flagging so the
  page never blanks; scraper exits non-zero only if ALL zips fail; workflows
  tolerate partial failure (still commit what succeeded).
- Page: fetch failure → inline error, last-good data already committed.

## Testing
- pytest on parsing/merge/history logic with a recorded real fixture (no network).
- Live smoke: `scraper.py --print --zips 22207` (non-blocking in CI).
- Manual: run full scraper, inspect JSON, open page locally.

## Out of scope (YAGNI)
Diesel/premium/E85, maps, service worker/PWA, >30-day history, other data
sources, user accounts.