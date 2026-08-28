"""Tests for scraper_lib — parsing, merging, history. No network."""

import json
import os
import re
from datetime import UTC, datetime, timedelta

import pytest

import scraper_lib as sl

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "location_22207.json")


@pytest.fixture
def raw_22207():
    with open(FIXTURE) as f:
        return json.load(f)


def _entry(raw, zip_code="22207"):
    return sl.parse_location(raw, zip_code, now="2026-08-27T19:05:00Z")


# --- parse_location ---

def test_parse_trends(raw_22207):
    e = _entry(raw_22207)
    assert e["zip"] == "22207"
    assert e["areaName"] == "Virginia"
    assert e["avg"] == 3.88
    assert e["low"] == 3.35
    assert e["stationCount"] == 9
    assert e["stale"] is False
    assert e["lastUpdated"] == "2026-08-27T19:05:00Z"


def test_parse_stations_sorted_cheapest_first_no_zero_prices(raw_22207):
    e = _entry(raw_22207)
    prices = [s["price"] for s in e["stations"]]
    assert prices == sorted(prices)
    assert all(p > 0 for p in prices)
    assert e["stations"][0]["price"] == min(prices)


def test_parse_station_shape(raw_22207):
    e = _entry(raw_22207)
    s0 = e["stations"][0]
    assert set(s0) == {"name", "address", "price", "updated"}
    assert s0["name"] == "BP"
    assert "5601 Lee Highway" in s0["address"]
    assert "Arlington" in s0["address"]
    assert "VA" in s0["address"]
    assert s0["updated"] == "2026-08-27T18:08:52.879Z"


def test_parse_caps_at_ten_stations(raw_22207):
    # fixture has 9; synth a 15-station payload to prove the cap
    raw = json.loads(json.dumps(raw_22207))
    base = raw["data"]["locationBySearchTerm"]["stations"]["results"][0]
    raw["data"]["locationBySearchTerm"]["stations"]["results"] = [
        dict(base, id=str(i), name=f"S{i}", prices=[
            {"credit": {"price": 4.0 - i * 0.01, "formattedPrice": "x",
                        "nickname": "n", "postedTime": "2026-08-27T18:00:00Z"},
             "fuelProduct": "regular_gas"}])
        for i in range(15)
    ]
    e = _entry(raw)
    assert len(e["stations"]) == 10
    assert e["stationCount"] == 15
    assert e["stations"][0]["price"] == pytest.approx(4.0 - 14 * 0.01)  # lowest first
    assert e["stations"][-1]["price"] == pytest.approx(4.0 - 5 * 0.01)


def test_parse_handles_nulls_and_missing(raw_22207):
    raw = json.loads(json.dumps(raw_22207))
    loc = raw["data"]["locationBySearchTerm"]
    loc["trends"] = []
    loc["stations"]["results"] = [
        {"name": "Ghost", "address": None, "prices": [
            {"credit": None, "fuelProduct": "regular_gas"}]},
        {"name": "Diesel Only", "prices": [
            {"credit": {"price": 5.0}, "fuelProduct": "diesel"}]},
    ]
    e = _entry(raw)
    assert e["stations"] == []
    assert e["avg"] is None and e["low"] is None
    assert e["stationCount"] == 2  # area count, not priced-station count


# --- merge_latest ---

def _old_snapshot():
    return {"generated": "2026-08-26T23:05:00Z", "zips": {
        "22207": {"zip": "22207", "areaName": "Virginia", "avg": 3.90,
                  "low": 3.40, "stationCount": 9, "stale": False,
                  "lastUpdated": "2026-08-26T23:05:00Z", "stations": []},
        "15222": {"zip": "15222", "areaName": "Pennsylvania", "avg": 3.75,
                  "low": 3.29, "stationCount": 12, "stale": False,
                  "lastUpdated": "2026-08-26T23:05:00Z", "stations": []},
    }}


def test_merge_new_replaces_old():
    old = _old_snapshot()
    new_22207 = _entry(json.load(open(FIXTURE)))
    merged = sl.merge_latest(old, {"22207": new_22207}, now="2026-08-27T19:05:00Z")
    assert merged["zips"]["22207"]["avg"] == 3.88
    assert merged["zips"]["22207"]["stale"] is False
    assert merged["generated"] == "2026-08-27T19:05:00Z"


def test_merge_failed_zip_carried_as_stale():
    old = _old_snapshot()
    new_22207 = _entry(json.load(open(FIXTURE)))
    merged = sl.merge_latest(old, {"22207": new_22207}, ok_zips={"22207"},
                             now="2026-08-27T19:05:00Z")
    assert merged["zips"]["15222"]["stale"] is True
    assert merged["zips"]["15222"]["avg"] == 3.75  # old values kept
    assert merged["zips"]["22207"]["stale"] is False


def test_merge_new_zip_added():
    old = _old_snapshot()
    raw = json.load(open(FIXTURE))
    e = sl.parse_location(raw, "90210", now="2026-08-27T19:05:00Z")
    merged = sl.merge_latest(old, {"90210": e}, now="2026-08-27T19:05:00Z")
    assert merged["zips"]["90210"]["zip"] == "90210"


# --- append_history ---

def test_append_history_and_cap():
    now = datetime(2026, 8, 27, 19, 5, tzinfo=UTC)
    points = [{"t": (now - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "avg": 3.80, "low": 3.30} for d in range(40)]
    entry = _entry(json.load(open(FIXTURE)))
    pts = sl.append_history(points, entry, now)
    assert len(pts) <= 31  # 40 days of history + today, capped at 30-day window
    assert pts[-1]["avg"] == 3.88
    oldest = datetime.strptime(pts[0]["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert (now - oldest).days <= 30


def test_append_history_dedupes_same_day():
    now = datetime(2026, 8, 27, 19, 5, tzinfo=UTC)
    t_today = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    points = [{"t": t_today, "avg": 3.90, "low": 3.40}]  # earlier run today
    entry = _entry(json.load(open(FIXTURE)))
    pts = sl.append_history(points, entry, now)
    todays = [p for p in pts if p["t"][:10] == "2026-08-27"]
    assert len(todays) == 1 and todays[0]["avg"] == 3.88


# --- csrf extraction ---

def test_csrf_regex():
    html = '<script>window.gbcsrf = "abc123XYZ-_=";</script>'
    m = sl.CSRF_PATTERN.search(html)
    assert m and m.group(2) == "abc123XYZ-_="
    assert not sl.CSRF_PATTERN.search("<html>no token</html>")


def test_zip_validation():
    assert sl.valid_zip("22207")
    assert not sl.valid_zip("2220")
    assert not sl.valid_zip("22207-1234")
    assert not sl.valid_zip("abcde")
    assert not sl.valid_zip("")