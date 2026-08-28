# gas-tracker ⛽

Twice-daily gas price tracking for Arlington, VA + 27 major US metros
(including Pittsburgh), on a fast mobile-first GitHub Pages site.

**Live:** https://gastracker.live/ (custom domain; also at https://james-see.github.io/gas-tracker/)

- Average + lowest regular gas price per area
- 10 cheapest stations for the selected Arlington zipcode
- Metro ranking: 10 cheapest / 10 priciest
- 30-day sparkline + "30-day low" callout + week-over-week delta
- On-demand lookup for any US zipcode (see below)

## How it works

```
GitHub Actions (hourly cron, gated to 7am & 5pm ET)
  └─ scraper.py  (GasBuddy unofficial GraphQL API via curl_cffi)
       └─ commits data/latest.json + data/history/*.json
            └─ GitHub Pages serves index.html (static, zero build)
```

No server, no API keys, no database. The page is a single HTML file with
inline CSS/JS; data is plain JSON committed by the scraper.

## Data source & disclaimer

Prices come from [GasBuddy](https://www.gasbuddy.com) community
contributors, fetched via GasBuddy's **unofficial** GraphQL API (the same
endpoint used by the py-gasbuddy / Home Assistant ecosystem). This project
is not affiliated with GasBuddy. Prices are crowd-reported — verify at the
pump. If you use this heavily, support GasBuddy by using their app.

## On-demand zipcode lookup

The page can fetch any zipcode on demand by dispatching a GitHub Actions
workflow (`ondemand.yml`) that scrapes the zip and commits
`data/ondemand/<zip>.json`. Because browser calls to GitHub's API need a
token:

1. Create a [fine-grained PAT](https://github.com/settings/personal-access-tokens/new)
   scoped to **only this repo** with **Actions: read & write** permission.
2. Paste it into the ⚙️ setup section on the page. It is stored in your
   browser's localStorage and sent only to GitHub's API — never anywhere
   else, never committed.

Without a PAT, the lookup falls back to a search link on GasBuddy.com.

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                      # unit tests (recorded fixtures, no network)
python scraper.py --only 22207 --print     # live scrape, one location
python scraper.py --print   # full run (31 locations, ~3-5 min)
python -m http.server       # serve locally; open http://localhost:8000
```

Location list lives in `scraper.py` (`ARLINGTON` + `METRO_CITIES`).
Arlington zips use zip-level search (neighborhood stations); metros use
city-level search (city trend data + full station pool — bare downtown
zips like 15222 can return zero stations).

### Rate limiting

GasBuddy throttles bursts (~15 rapid calls → HTTP 429). The scraper
paces itself (2.5–5s jitter), backs off exponentially on 429s, and aborts
after 5 consecutive 429s. Failed locations keep their previous data,
flagged `stale` — the page never goes blank.

## License

MIT — see [LICENSE](LICENSE).