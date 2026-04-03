"""Generate snapshot CSV data for the bee-pollinator demo.

By default, fetches real data from the USDA NASS QuickStats API and saves
it as checked-in CSV snapshots. Falls back to deterministic sample data
if no API key is available.

Usage:
    # With API key (real NASS data):
    USDA_NASS_API_KEY=your_key python generate_snapshots.py

    # Without API key (deterministic sample data):
    python generate_snapshots.py

This product uses the NASS API but is not endorsed or certified by NASS.
"""

import csv
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SNAPSHOT_DIR = Path(__file__).parent.parent / "data" / "snapshots"
NASS_API_BASE = "https://quickstats.nass.usda.gov/api/api_GET/"

SKIP_STATES = {"other states", "us total", "united states"}


# ---------------------------------------------------------------------------
# Live NASS API fetch
# ---------------------------------------------------------------------------

def _fetch_nass(api_key: str, params: dict) -> list[dict]:
    """Fetch records from the USDA NASS QuickStats API."""
    params["key"] = api_key
    params["format"] = "JSON"
    qs = "&".join(
        f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items()
    )
    url = f"{NASS_API_BASE}?{qs}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    return data.get("data", [])


def _clean_val(v):
    if v is None:
        return ""
    v = str(v).strip().replace(",", "")
    if v in ("(D)", "(Z)", "(NA)", "(S)", ""):
        return ""
    return v


def _build_map(records: list[dict]) -> dict:
    m = {}
    for r in records:
        state = r["state_name"].strip().title()
        year = str(r["year"])
        val = _clean_val(r.get("Value"))
        if val and state.lower() not in SKIP_STATES:
            m[(state, year)] = val
    return m


def fetch_honey_production_snapshot(api_key: str) -> list[dict]:
    """Fetch and combine honey production, yield, colony, and price data."""
    prod = _fetch_nass(api_key, {
        "commodity_desc": "HONEY", "statisticcat_desc": "PRODUCTION",
        "year__GE": 2015, "agg_level_desc": "STATE", "unit_desc": "LB",
    })
    yields = _fetch_nass(api_key, {
        "commodity_desc": "HONEY", "statisticcat_desc": "PRODUCTION",
        "year__GE": 2015, "agg_level_desc": "STATE", "unit_desc": "LB / COLONY",
    })
    colonies = _fetch_nass(api_key, {
        "commodity_desc": "HONEY", "statisticcat_desc": "INVENTORY",
        "year__GE": 2015, "agg_level_desc": "STATE", "unit_desc": "COLONIES",
        "reference_period_desc": "MARKETING YEAR",
    })
    prices = _fetch_nass(api_key, {
        "commodity_desc": "HONEY", "statisticcat_desc": "PRICE RECEIVED",
        "year__GE": 2015, "agg_level_desc": "STATE",
    })

    yield_map = _build_map(yields)
    colony_map = _build_map(colonies)
    price_map = _build_map(prices)

    rows, seen = [], set()
    for r in prod:
        state = r["state_name"].strip().title()
        year = str(r["year"])
        if state.lower() in SKIP_STATES:
            continue
        production = _clean_val(r.get("Value"))
        if not production:
            continue
        key = (state, year)
        if key in seen:
            continue
        seen.add(key)

        price_cents = price_map.get(key, "")
        price_dollars = ""
        if price_cents:
            try:
                price_dollars = str(round(float(price_cents) / 100, 2))
            except ValueError:
                price_dollars = price_cents

        rows.append({
            "state": state, "year": year, "production": production,
            "yield_per_colony": yield_map.get(key, ""),
            "colonies": colony_map.get(key, ""),
            "price_per_lb": price_dollars,
        })
    rows.sort(key=lambda x: (x["state"], x["year"]))
    return rows


def fetch_colony_loss_snapshot(api_key: str) -> list[dict]:
    """Fetch quarterly colony loss data (pct and absolute)."""
    quarter_map = {
        "JAN THRU MAR": "Q1", "APR THRU JUN": "Q2",
        "JUL THRU SEP": "Q3", "OCT THRU DEC": "Q4",
    }

    loss_pct = _fetch_nass(api_key, {
        "commodity_desc": "HONEY", "statisticcat_desc": "LOSS, DEADOUT",
        "year__GE": 2015, "agg_level_desc": "STATE",
        "unit_desc": "PCT OF COLONIES",
    })
    loss_abs = _fetch_nass(api_key, {
        "commodity_desc": "HONEY", "statisticcat_desc": "LOSS, DEADOUT",
        "year__GE": 2015, "agg_level_desc": "STATE", "unit_desc": "COLONIES",
    })

    pct_map, abs_map = {}, {}
    for r in loss_pct:
        state = r["state_name"].strip().title()
        year = str(r["year"])
        q = quarter_map.get(r.get("reference_period_desc", ""), "")
        val = _clean_val(r.get("Value"))
        if val and q and state.lower() not in SKIP_STATES:
            pct_map[(state, year, q)] = val
    for r in loss_abs:
        state = r["state_name"].strip().title()
        year = str(r["year"])
        q = quarter_map.get(r.get("reference_period_desc", ""), "")
        val = _clean_val(r.get("Value"))
        if val and q and state.lower() not in SKIP_STATES:
            abs_map[(state, year, q)] = val

    all_keys = sorted(set(list(pct_map.keys()) + list(abs_map.keys())))
    rows = []
    for state, year, quarter in all_keys:
        rows.append({
            "state": state, "year": year, "quarter": quarter,
            "loss_pct": pct_map.get((state, year, quarter), ""),
            "loss_colonies": abs_map.get((state, year, quarter), ""),
        })
    return rows


def fetch_colony_stressors_snapshot(api_key: str) -> list[dict]:
    """Fetch quarterly colony stressor data (pct of colonies affected)."""
    import re

    quarter_map = {
        "JAN THRU MAR": "Q1", "APR THRU JUN": "Q2",
        "JUL THRU SEP": "Q3", "OCT THRU DEC": "Q4",
    }

    records = _fetch_nass(api_key, {
        "commodity_desc": "HONEY", "statisticcat_desc": "INVENTORY",
        "unit_desc": "PCT OF COLONIES",
        "year__GE": 2015, "agg_level_desc": "STATE",
    })

    rows = []
    for r in records:
        state = r["state_name"].strip().title()
        if state.lower() in SKIP_STATES:
            continue
        year = str(r["year"])
        q = quarter_map.get(r.get("reference_period_desc", ""), "")
        if not q:
            continue
        val = _clean_val(r.get("Value"))
        if not val:
            continue

        desc = r.get("short_desc", "")
        # Extract stressor from "AFFECTED BY <stressor> - INVENTORY"
        m = re.search(r"AFFECTED BY (.+?) - INVENTORY", desc)
        if m:
            stressor = m.group(1).strip().title()
        elif "RENOVATED" in desc:
            stressor = "Renovated"
        else:
            continue

        rows.append({
            "state": state, "year": year, "quarter": q,
            "stressor": stressor, "pct_affected": val,
        })

    rows.sort(key=lambda x: (x["state"], x["year"], x["quarter"], x["stressor"]))
    return rows


# ---------------------------------------------------------------------------
# Deterministic sample data (no API key needed)
# ---------------------------------------------------------------------------

STATE_PRODUCTION_BASELINES = {
    "North Dakota": 38000, "California": 13500, "South Dakota": 15000,
    "Montana": 14000, "Florida": 12000, "Texas": 9000, "Michigan": 5500,
    "Minnesota": 7500, "Georgia": 4800, "Louisiana": 4200,
    "Wisconsin": 4000, "Oregon": 3800, "New York": 3500, "Idaho": 3200,
    "Washington": 3000, "Mississippi": 2800, "Iowa": 2600, "Nebraska": 2400,
    "North Carolina": 2200, "Pennsylvania": 2000, "Ohio": 1800,
    "Virginia": 1600, "Arkansas": 1400, "Hawaii": 1200, "Tennessee": 1100,
    "Alabama": 1000, "Indiana": 950, "Kansas": 900, "Arizona": 850,
    "New Jersey": 800, "Colorado": 750, "Utah": 700, "Illinois": 650,
    "Oklahoma": 600, "Kentucky": 550, "Maine": 500, "Vermont": 450,
    "South Carolina": 400, "Maryland": 350, "West Virginia": 300,
    "Connecticut": 250, "New Mexico": 230, "Missouri": 220,
}
YEARS = list(range(2015, 2025))
LOSS_STATES = [
    "California", "North Dakota", "Montana", "Florida", "Texas",
    "South Dakota", "Michigan", "Minnesota", "Georgia", "Louisiana",
    "Wisconsin", "Oregon", "New York", "Idaho", "Washington",
    "Mississippi", "Iowa", "Nebraska", "North Carolina", "Pennsylvania",
    "Ohio", "Virginia", "Arkansas", "Hawaii", "Tennessee",
]


def _seeded_variation(state, year, base, pct):
    h = int(hashlib.md5(f"{state}{year}".encode()).hexdigest(), 16)
    factor = 1.0 + (((h % 10000) / 10000.0) * 2 - 1) * pct
    return base * factor


def generate_honey_production_sample() -> list[dict]:
    rows = []
    for state, base_prod in STATE_PRODUCTION_BASELINES.items():
        for year in YEARS:
            trend = 1.0 - (year - 2015) * 0.01
            production = round(_seeded_variation(state, year, base_prod * trend, 0.15))
            if production < 100:
                production = 100
            base_yield = 55 if base_prod > 5000 else 45
            yield_per_colony = round(_seeded_variation(state, year, base_yield, 0.20), 1)
            colonies = max(1000, round(production * 1000 / max(yield_per_colony, 1)))
            base_price = 4.50 + (year - 2015) * 0.35
            price_per_lb = round(_seeded_variation(state, year, base_price, 0.15), 2)
            rows.append({
                "state": state, "year": year, "production": production,
                "yield_per_colony": yield_per_colony, "colonies": colonies,
                "price_per_lb": price_per_lb,
            })
    return rows


def generate_colony_loss_sample() -> list[dict]:
    rows = []
    for state in LOSS_STATES:
        for year in YEARS:
            for qi, quarter in enumerate(["Q1", "Q2", "Q3", "Q4"], 1):
                base_loss = 30 + (hash(f"{state}{year}") % 20)
                seasonal = [1.2, 0.7, 0.8, 1.0][qi - 1]
                loss_pct = round(base_loss * seasonal)
                loss_colonies = round(loss_pct * 50)
                rows.append({
                    "state": state, "year": year, "quarter": quarter,
                    "loss_pct": loss_pct, "loss_colonies": loss_colonies,
                })
    return rows

def generate_colony_stressors_sample() -> list[dict]:
    stressors = ["Varroa Mites", "Pesticides", "Disease",
                 "Pests (Excl Varroa Mites)", "Other Causes", "Unknown Causes"]
    base_pcts = {"Varroa Mites": 35, "Pesticides": 15, "Disease": 8,
                 "Pests (Excl Varroa Mites)": 12, "Other Causes": 10, "Unknown Causes": 5}
    rows = []
    for state in LOSS_STATES:
        for year in YEARS:
            for qi, quarter in enumerate(["Q1", "Q2", "Q3", "Q4"], 1):
                for stressor in stressors:
                    base = base_pcts[stressor]
                    pct = round(_seeded_variation(
                        f"{state}{stressor}", year, base, 0.30), 1)
                    pct = max(0, min(pct, 100))
                    rows.append({
                        "state": state, "year": year, "quarter": quarter,
                        "stressor": stressor, "pct_affected": pct,
                    })
    return rows


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def write_csv(rows: list[dict], filename: str):
    path = SNAPSHOT_DIR / filename
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    size_kb = path.stat().st_size / 1024
    print(f"  {filename}: {len(rows)} rows, {size_kb:.1f} KB")


def main():
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    api_key = os.getenv("USDA_NASS_API_KEY")

    if api_key:
        print("USDA_NASS_API_KEY found — fetching live NASS data...\n")
        try:
            honey_rows = fetch_honey_production_snapshot(api_key)
            loss_rows = fetch_colony_loss_snapshot(api_key)
            stressor_rows = fetch_colony_stressors_snapshot(api_key)
            write_csv(honey_rows, "honey_production.csv")
            write_csv(loss_rows, "colony_loss.csv")
            write_csv(stressor_rows, "colony_stressors.csv")
        except Exception as e:
            print(f"  API fetch failed: {e}")
            print("  Falling back to sample data...\n")
            write_csv(generate_honey_production_sample(), "honey_production.csv")
            write_csv(generate_colony_loss_sample(), "colony_loss.csv")
            write_csv(generate_colony_stressors_sample(), "colony_stressors.csv")
    else:
        print("No USDA_NASS_API_KEY — generating deterministic sample data...\n")
        write_csv(generate_honey_production_sample(), "honey_production.csv")
        write_csv(generate_colony_loss_sample(), "colony_loss.csv")
        write_csv(generate_colony_stressors_sample(), "colony_stressors.csv")

    print(f"\nDone. Snapshots in: {SNAPSHOT_DIR}")


if __name__ == "__main__":
    main()
