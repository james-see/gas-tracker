"""GasBuddy unofficial API client + data normalization for gas-tracker."""

import re
import time
from datetime import UTC, datetime, timedelta

BASE_URL = "https://www.gasbuddy.com/graphql"
HOME_URL = "https://www.gasbuddy.com/home"

CSRF_PATTERN = re.compile(r'window\.gbcsrf\s*=\s*(["\'])(.*?)\1')
ZIP_PATTERN = re.compile(r"^\d{5}$")

DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Sec-Fetch-Dest": "",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Priority": "u=0",
    "apollo-require-preflight": "true",
    "Origin": "https://www.gasbuddy.com",
    "Referer": HOME_URL,
}

LOCATION_QUERY = (
    "query LocationBySearchTerm($search: String) {"
    " locationBySearchTerm(search: $search) {"
    " trends { areaName country today todayLow }"
    " stations { count results { id name latitude longitude distance fuels"
    " address { line1 locality region postalCode }"
    " prices { credit { price formattedPrice nickname postedTime } fuelProduct }"
    " } } } }"
)

REGULAR = "regular_gas"


def valid_zip(z: str) -> bool:
    return bool(ZIP_PATTERN.match(z or ""))


def slugify(text: str) -> str:
    """'Pittsburgh, PA' -> 'pittsburgh-pa' (storage key for city searches)."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_location(raw: dict, key: str, search: str | None = None,
                   label: str = "", now: str | None = None) -> dict:
    """Normalize a LocationBySearchTerm response into a location entry dict.

    `key` is the storage id (a zipcode, or a slug like "pittsburgh-pa");
    `search` is the term sent to GasBuddy (defaults to key); `label` is the
    display name (defaults to key).
    """
    search = search or key
    now = now or _utcnow_iso()
    loc = (raw.get("data") or {}).get("locationBySearchTerm") or {}
    trends = loc.get("trends") or []
    trend = trends[0] if trends else {}

    results = ((loc.get("stations") or {}).get("results")) or []
    stations = []
    for st in results:
        price = None
        updated = None
        for p in st.get("prices") or []:
            if p.get("fuelProduct") != REGULAR:
                continue
            credit = p.get("credit") or {}
            val = credit.get("price")
            if val and float(val) > 0:
                price = float(val)
                updated = credit.get("postedTime")
            break
        if price is not None:
            addr = st.get("address") or {}
            stations.append({
                "name": st.get("name") or "Unknown",
                "address": ", ".join(
                    x for x in (addr.get("line1"), addr.get("locality"),
                                addr.get("region")) if x
                ),
                "price": price,
                "updated": updated,
            })
    stations.sort(key=lambda s: s["price"])
    stations = stations[:10]

    avg = trend.get("today")
    low = trend.get("todayLow")
    return {
        "key": key,
        "label": label or key,
        "search": search,
        "areaName": trend.get("areaName"),
        "avg": float(avg) if avg else None,
        "low": float(low) if low else None,
        "stationCount": len(results),
        "stations": stations,
        "stale": False,
        "lastUpdated": now,
    }


def merge_latest(old: dict | None, new_entries: dict[str, dict],
                 ok_keys: set[str] | None = None, now: str | None = None,
                 partial: bool = False) -> dict:
    """Merge fresh location entries into the previous latest.json document.

    Locations not fetched successfully this run are carried forward from `old`
    and flagged stale=True — unless `partial` is set (a subset run, e.g.
    --only), in which case unattempted locations are carried as-is.
    Returns the full latest.json document.
    """
    now = now or _utcnow_iso()
    old_locs = (old or {}).get("locations") or {}
    ok_keys = ok_keys if ok_keys is not None else set(new_entries)

    locs: dict[str, dict] = {}
    for k, entry in old_locs.items():
        if k in ok_keys:
            continue  # replaced by fresh data below
        carried = dict(entry)
        if not partial:
            carried["stale"] = True
        locs[k] = carried
    for k, entry in new_entries.items():
        locs[k] = entry
    return {"generated": now, "locations": locs}


def append_history(points: list[dict], entry: dict, now: datetime,
                   max_days: int = 30) -> list[dict]:
    """Append today's avg/low to history, dedupe same-day (latest wins), cap window."""
    t = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    today = t[:10]
    pts = [p for p in (points or []) if p.get("t", "")[:10] != today]
    if entry.get("avg") is not None:
        pts.append({"t": t, "avg": entry["avg"], "low": entry["low"]})
    cutoff = now - timedelta(days=max_days)
    out = []
    for p in pts:
        try:
            pt_dt = datetime.strptime(p["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except (ValueError, TypeError, KeyError):
            continue
        if pt_dt >= cutoff:
            out.append(p)
    out.sort(key=lambda p: p["t"])
    return out


class GasBuddyClient:
    """Client for GasBuddy's unofficial GraphQL API (Chrome TLS impersonation)."""

    def __init__(self, timeout: int = 30):
        from curl_cffi import requests as cc_requests
        self._cc = cc_requests
        self._timeout = timeout
        self._session = cc_requests.Session(impersonate="chrome")
        self._csrf: str | None = None

    def get_csrf(self) -> str:
        """Fetch /home and extract the window.gbcsrf token."""
        r = self._session.get(HOME_URL, timeout=self._timeout)
        if r.status_code != 200:
            raise RuntimeError(f"home page HTTP {r.status_code}")
        m = CSRF_PATTERN.search(r.text)
        if not m:
            raise RuntimeError("csrf token not found in home page")
        token = m.group(2)
        self._csrf = token
        return token

    def location_search(self, search: str, retries: int = 3,
                        backoff: float = 1.0) -> dict:
        """POST LocationBySearchTerm for a search term (zip or 'City, ST').

        Retries with fresh CSRF on auth/token failures and with long waits on
        429 rate limits. `backoff` is a multiplier the caller can raise after
        observing throttling (the caller's global pace control).
        Returns the parsed JSON dict.
        """
        search = (search or "").strip()
        if not search:
            raise ValueError("empty search term")
        last_err: Exception | None = None
        for attempt in range(retries):
            if not self._csrf:
                self.get_csrf()
            payload = {
                "operationName": "LocationBySearchTerm",
                "variables": {"fuel": 1, "maxAge": 3, "search": search},
                "query": LOCATION_QUERY,
            }
            headers = dict(DEFAULT_HEADERS)
            headers["gbcsrf"] = self._csrf
            try:
                r = self._session.post(BASE_URL, json=payload,
                                       headers=headers, timeout=self._timeout)
            except Exception as e:  # transport-level
                last_err = e
                self._csrf = None
                continue
            if r.status_code == 200:
                data = r.json()
                if data.get("errors"):
                    last_err = RuntimeError(f"graphql errors: {data['errors']}")
                    self._csrf = None
                    continue
                return data
            if r.status_code == 429:
                wait = min(30 * (2 ** attempt) * backoff, 120)
                last_err = RuntimeError("HTTP 429 rate limited")
                time.sleep(wait)
                continue
            if r.status_code in (401, 403) or "Bad Request" in (r.text or "")[:200]:
                # token-suspect: refresh CSRF and retry
                self._csrf = None
                last_err = RuntimeError(f"HTTP {r.status_code}")
                continue
            r.raise_for_status()
        raise RuntimeError(
            f"location_search failed for {search!r} after {retries} attempts: {last_err}")