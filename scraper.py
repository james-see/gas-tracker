#!/usr/bin/env python3
"""gas-tracker scraper: pull GasBuddy prices, write data/*.json.

Usage:
  python scraper.py                          # all tracked locations -> data/
  python scraper.py --only 22207,pittsburgh-pa
  python scraper.py --zip 90210              # ondemand lookup only
  python scraper.py --print                  # also print JSON to stdout
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import UTC, datetime

from scraper_lib import (GasBuddyClient, append_history, merge_latest,
                         parse_location, slugify, valid_zip)

# Arlington zipcodes first (default view, neighborhood-level stations),
# then major metros searched city-wide (city-level trends + full station pool).
ARLINGTON = ["22207", "22201", "22204", "22202"]
METRO_CITIES = [
    "New York, NY", "Los Angeles, CA", "Chicago, IL", "Houston, TX",
    "Phoenix, AZ", "Philadelphia, PA", "San Antonio, TX", "San Diego, CA",
    "Dallas, TX", "San Jose, CA", "Austin, TX", "Jacksonville, FL",
    "Columbus, OH", "Seattle, WA", "Denver, CO", "Boston, MA",
    "Nashville, TN", "Atlanta, GA", "Miami, FL", "Detroit, MI",
    "Minneapolis, MN", "Pittsburgh, PA", "St. Louis, MO", "Tampa, FL",
    "Portland, OR", "Las Vegas, NV", "Washington, DC",
]


def locations() -> list[dict]:
    """Tracked locations: [{key, search, label}] in display order."""
    locs = [{"key": z, "search": z, "label": f"Arlington {z}"} for z in ARLINGTON]
    locs += [{"key": slugify(c), "search": c, "label": c}
             for c in METRO_CITIES]
    return locs


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_dt() -> datetime:
    return datetime.now(UTC)


def atomic_write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def load_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def history_path(out_dir: str, key: str) -> str:
    return os.path.join(out_dir, "history", f"{key}.json")


def update_history(out_dir: str, key: str, entry: dict) -> None:
    hp = history_path(out_dir, key)
    old = load_json(hp) or {"key": key, "points": []}
    old["key"] = key
    old["points"] = append_history(old.get("points") or [], entry, _now_dt())
    atomic_write_json(hp, old)


def fetch_all(only: list[str] | None, out_dir: str, do_print: bool) -> int:
    latest_path = os.path.join(out_dir, "latest.json")
    old = load_json(latest_path)
    locs = locations()
    if only:
        want = set(only)
        locs = [l for l in locs if l["key"] in want or l["search"] in want]
        missing = want - {l["key"] for l in locs}
        if missing:
            print(f"[warn] unknown keys ignored: {sorted(missing)}", file=sys.stderr)
    client = GasBuddyClient()
    entries: dict[str, dict] = {}
    ok_keys: set[str] = set()
    backoff = 1.0       # grows when we hit 429s; never shrinks within a run
    consecutive_429 = 0

    for i, loc in enumerate(locs):
        if i:
            time.sleep(random.uniform(2.5, 5.0) * backoff)  # polite pacing
        try:
            raw = client.location_search(loc["search"], backoff=backoff)
            entry = parse_location(raw, loc["key"], search=loc["search"],
                                   label=loc["label"], now=_now_iso())
            entries[loc["key"]] = entry
            ok_keys.add(loc["key"])
            consecutive_429 = 0
            print(f"[ok] {loc['label']}: avg={entry['avg']} low={entry['low']} "
                  f"stations={entry['stationCount']}")
        except Exception as e:
            msg = str(e)
            if "429" in msg:
                consecutive_429 += 1
                backoff = min(backoff * 2, 8.0)  # slow the whole run down
                if consecutive_429 >= 5:
                    print("[error] 5 consecutive 429s — aborting run to let "
                          "the rate limit cool down", file=sys.stderr)
                    break
            print(f"[fail] {loc['label']}: {e}", file=sys.stderr)

    if not ok_keys:
        print("[error] all locations failed; leaving data untouched",
              file=sys.stderr)
        return 1

    partial = bool(only)  # subset runs must not stale-flag unattempted locations
    merged = merge_latest(old, entries, ok_keys=ok_keys, now=_now_iso(),
                          partial=partial)
    atomic_write_json(latest_path, merged)
    for k in ok_keys:
        update_history(out_dir, k, entries[k])
    if do_print:
        print(json.dumps(merged, indent=1))
    print(f"[done] {len(ok_keys)}/{len(locs)} locations updated -> {latest_path}")
    return 0


def fetch_single_zip(zip_code: str, out_dir: str, do_print: bool) -> int:
    """On-demand zipcode lookup -> data/ondemand/<zip>.json."""
    if not valid_zip(zip_code):
        print(f"[error] invalid zip: {zip_code!r}", file=sys.stderr)
        return 2
    client = GasBuddyClient()
    try:
        raw = client.location_search(zip_code)
    except Exception as e:
        print(f"[error] {zip_code}: {e}", file=sys.stderr)
        return 1
    entry = parse_location(raw, zip_code, search=zip_code, label=zip_code,
                           now=_now_iso())
    path = os.path.join(out_dir, "ondemand", f"{zip_code}.json")
    atomic_write_json(path, entry)
    update_history(out_dir, zip_code, entry)
    if do_print:
        print(json.dumps(entry, indent=1))
    print(f"[done] {zip_code} -> {path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="gas-tracker GasBuddy scraper")
    ap.add_argument("--only", metavar="KEYS",
                    help="comma-separated location keys/searches to fetch")
    ap.add_argument("--out-dir", default="data")
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--zip", metavar="ZIP",
                    help="fetch one zipcode into data/ondemand/ (no latest.json update)")
    args = ap.parse_args()

    if args.zip:
        return fetch_single_zip(args.zip.strip(), args.out_dir, args.do_print)
    only = [k.strip() for k in args.only.split(",")] if args.only else None
    return fetch_all(only, args.out_dir, args.do_print)


if __name__ == "__main__":
    sys.exit(main())