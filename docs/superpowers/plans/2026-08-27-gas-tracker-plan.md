# Gas Tracker Implementation Plan

> **For agentic workers:** Use executing-plans to implement task-by-task. Steps use checkbox syntax.

**Goal:** Twice-daily GasBuddy scraper (Actions) + zero-build GitHub Pages dashboard for Arlington zips + major metros, with 30-day history and on-demand zip lookup.

**Architecture:** Python scraper (curl_cffi + CSRF) → commits JSON to `data/` → Pages serves single-file HTML reading JSON. On-demand via workflow_dispatch + PAT in visitor's localStorage.

**Tech Stack:** Python 3.11+, curl_cffi, pytest, GitHub Actions, vanilla JS/HTML/CSS.

## Global Constraints
- npm/yarn not involved; no build step for the page; no server.
- Scraper deps pinned in `requirements.txt`: curl_cffi, pytest (dev in requirements-dev.txt).
- Prepared JSON shape exactly as spec (`docs/superpowers/specs/2026-08-27-gas-tracker-design.md`).
- Pittsburgh (15222) in metros. Arlington zips first in ZIPS ordering.
- Attribution to GasBuddy contributors on page footer + README; unofficial-API disclaimer.
- Workflows: ET-hour gate for 7am/5pm; `concurrency` guard; atomic JSON writes; commit data to main directly.

---

### Task 1: scraper_lib (client + parsing)
Files: `scraper_lib.py`, `tests/fixtures/location_22207.json`, `tests/test_scraper_lib.py`
- GasBuddyClient: `get_csrf()` (GET /home, regex `window\.gbcsrf\s*=\s*(["'])(.*?)\1`), `location_search(zip)` with 3 retries + fresh CSRF on 401/403; session impersonate="chrome".
- `parse_location(raw, zip)` → zip entry dict; credit price for `regular_gas`; stations sorted asc, top 10, address joined.
- `merge_latest(old, new)` → stale-flag carryover; `append_history(points, entry, now)` → 30-day cap.
- Test: fixture-based parse + merge + history cap. Commit.

### Task 2: scraper CLI
Files: `scraper.py`
- `--zips CSV`, `--out-dir`, `--print`, `--single ZIP`; one CSRF per run; 1–3s jitter; merges + atomic write (`tmp` + `os.replace`); exit 1 iff all zips fail. Live-verify against 22207 + 15222. Commit.

### Task 3: frontend index.html
Files: `index.html`, `data/` (from Task 2 run)
- Sections per spec; inline SVG sparkline; metro top/bottom 10; all-metros grid; on-demand PAT flow + poll + link-out fallback; stale badges; footer attribution. Mobile-first, dark mode, 44px targets. Verify locally via preview with real data. Commit.

### Task 4: workflows
Files: `.github/workflows/{update-prices.yml,ondemand.yml,ci.yml,deploy-pages.yml}`
- update-prices: hourly cron + `TZ=America/New_York` hour gate (7/17) + dispatch; runs scraper; commits data/ if changed.
- ondemand: dispatch with `zip` (validated `^[0-9]{5}$`), `--single`, writes ondemand + history, commits.
- ci: pytest + non-blocking live smoke (22207).
- deploy-pages: paths-filtered push to main + manual; upload-pages-artifact → deploy-pages; `fetch-depth: 0` not needed; artifact includes index.html + data/.
- Commit.

### Task 5: repo meta + push + Pages
Files: `README.md` (setup, PAT how-to, attribution, disclaimer), `AGENTS.md` (conventions), `.gitignore`, `LICENSE` (MIT), `requirements.txt`, `requirements-dev.txt`
- Create GitHub repo `james-see/gas-tracker`, push, enable Pages (build_type=workflow), verify deployment + live JSON, first scheduled run sanity.