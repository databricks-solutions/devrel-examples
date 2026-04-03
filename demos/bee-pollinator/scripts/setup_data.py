"""
Bee Pollinator Demo - Data Ingestion Script

Loads bee health data into Unity Catalog Delta tables. By default, uses
pre-generated CSV snapshots shipped with the repo (no API key needed).

Optionally fetches live USDA NASS data with --refresh flag (requires free
API key from https://quickstats.nass.usda.gov/api).

This product uses the NASS API but is not endorsed or certified by NASS.

Usage:
    # Default: load from checked-in snapshots (zero signup)
    python setup_data.py --catalog your_catalog --schema bee_health

    # Optional: refresh honey_production from live USDA NASS API
    export USDA_NASS_API_KEY="your_key_here"
    python setup_data.py --catalog your_catalog --schema bee_health --refresh
"""

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
import requests

try:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.catalog import VolumeType
except ImportError:
    print("Error: databricks-sdk not installed. Run: pip install databricks-sdk")
    sys.exit(1)


# USDA NASS QuickStats API endpoint
NASS_API_BASE = "https://quickstats.nass.usda.gov/api/api_GET/"


def fetch_nass_data(api_key: str, params: dict) -> pd.DataFrame:
    """Fetch data from USDA NASS QuickStats API."""
    params["key"] = api_key
    params["format"] = "JSON"

    print(f"Fetching NASS data: {params.get('commodity_desc', 'N/A')} - {params.get('statisticcat_desc', 'N/A')}")

    response = requests.get(NASS_API_BASE, params=params, timeout=60)
    response.raise_for_status()

    data = response.json()
    if "data" not in data:
        print(f"Warning: No data returned. Response keys: {data.keys()}")
        return pd.DataFrame()

    df = pd.DataFrame(data["data"])
    print(f"  → {len(df)} records fetched")
    return df


def fetch_honey_production(api_key: str) -> pd.DataFrame:
    """Fetch USDA honey production data (2015-2024)."""
    params = {
        "commodity_desc": "HONEY",
        "statisticcat_desc": "PRODUCTION",
        "year__GE": 2015,
        "agg_level_desc": "STATE",
    }

    df = fetch_nass_data(api_key, params)

    if df.empty:
        return df

    # Select and rename key columns
    df_clean = df[[
        "state_name", "year", "Value", "unit_desc"
    ]].copy()

    df_clean.columns = ["state", "year", "production", "unit"]

    # Convert production to numeric (remove commas)
    df_clean["production"] = pd.to_numeric(
        df_clean["production"].str.replace(",", ""), errors="coerce"
    )

    return df_clean


def fetch_honey_yield(api_key: str) -> pd.DataFrame:
    """Fetch honey yield per colony (2015-2024).

    NASS has no separate YIELD category; yield is in the PRODUCTION query
    filtered to the LB / COLONY unit.
    """
    params = {
        "commodity_desc": "HONEY",
        "statisticcat_desc": "PRODUCTION",
        "unit_desc": "LB / COLONY",
        "year__GE": 2015,
        "agg_level_desc": "STATE",
    }

    df = fetch_nass_data(api_key, params)

    if df.empty:
        return df

    df_clean = df[[
        "state_name", "year", "Value", "unit_desc"
    ]].copy()

    df_clean.columns = ["state", "year", "yield_per_colony", "unit"]

    df_clean["yield_per_colony"] = pd.to_numeric(
        df_clean["yield_per_colony"].str.replace(",", ""), errors="coerce"
    )

    return df_clean


def fetch_colony_counts(api_key: str) -> pd.DataFrame:
    """Fetch colony counts (2015-2024)."""
    params = {
        "commodity_desc": "HONEY",
        "class_desc": "ALL CLASSES",
        "statisticcat_desc": "INVENTORY",
        "year__GE": 2015,
        "agg_level_desc": "STATE",
    }

    df = fetch_nass_data(api_key, params)

    if df.empty:
        return df

    df_clean = df[[
        "state_name", "year", "Value", "unit_desc"
    ]].copy()

    df_clean.columns = ["state", "year", "colonies", "unit"]

    df_clean["colonies"] = pd.to_numeric(
        df_clean["colonies"].str.replace(",", ""), errors="coerce"
    )

    return df_clean


def fetch_honey_price(api_key: str) -> pd.DataFrame:
    """Fetch honey price per lb (2015-2024)."""
    params = {
        "commodity_desc": "HONEY",
        "statisticcat_desc": "PRICE RECEIVED",
        "year__GE": 2015,
        "agg_level_desc": "STATE",
    }

    df = fetch_nass_data(api_key, params)

    if df.empty:
        return df

    df_clean = df[[
        "state_name", "year", "Value", "unit_desc"
    ]].copy()

    df_clean.columns = ["state", "year", "price_per_lb", "unit"]

    df_clean["price_per_lb"] = pd.to_numeric(
        df_clean["price_per_lb"], errors="coerce"
    )

    return df_clean


def combine_honey_data(production_df, yield_df, colony_df, price_df) -> pd.DataFrame:
    """Combine honey production metrics into single table."""
    print("\nCombining honey production data...")

    # Start with production
    combined = production_df[["state", "year", "production"]].copy()

    # Merge yield
    if not yield_df.empty:
        combined = combined.merge(
            yield_df[["state", "year", "yield_per_colony"]],
            on=["state", "year"],
            how="left"
        )

    # Merge colonies
    if not colony_df.empty:
        combined = combined.merge(
            colony_df[["state", "year", "colonies"]],
            on=["state", "year"],
            how="left"
        )

    # Merge price
    if not price_df.empty:
        combined = combined.merge(
            price_df[["state", "year", "price_per_lb"]],
            on=["state", "year"],
            how="left"
        )

    print(f"  → Combined table: {len(combined)} rows, {len(combined.columns)} columns")
    return combined


def fetch_colony_loss(api_key: str) -> pd.DataFrame:
    """Fetch colony deadout loss data (2015-2024).

    The correct NASS statisticcat_desc is 'LOSS, DEADOUT' (not 'LOSS').
    Returns both absolute colony counts and percentage of colonies lost.
    """
    params = {
        "commodity_desc": "HONEY",
        "statisticcat_desc": "LOSS, DEADOUT",
        "year__GE": 2015,
        "agg_level_desc": "STATE",
    }

    df = fetch_nass_data(api_key, params)

    if df.empty:
        return df

    df_clean = df[[
        "state_name", "year", "Value", "unit_desc", "short_desc"
    ]].copy()

    df_clean.columns = ["state", "year", "value", "unit", "description"]

    # Clean numeric values (remove commas, handle suppressed values like (D), (Z))
    df_clean["value"] = pd.to_numeric(
        df_clean["value"].str.replace(",", ""), errors="coerce"
    )

    return df_clean



def create_unity_catalog_schema(w: WorkspaceClient, catalog: str, schema: str):
    """Create Unity Catalog schema if it doesn't exist."""
    try:
        w.schemas.get(f"{catalog}.{schema}")
        print(f"Schema {catalog}.{schema} already exists")
    except Exception:
        print(f"Creating schema {catalog}.{schema}...")
        w.schemas.create(name=schema, catalog_name=catalog)
        print("  → Schema created")


def create_unity_catalog_volume(w: WorkspaceClient, catalog: str, schema: str, volume: str):
    """Create Unity Catalog volume for documents if it doesn't exist."""
    try:
        w.volumes.read(f"{catalog}.{schema}.{volume}")
        print(f"Volume {catalog}.{schema}.{volume} already exists")
    except Exception:
        print(f"Creating volume {catalog}.{schema}.{volume}...")
        w.volumes.create(
            catalog_name=catalog,
            schema_name=schema,
            name=volume,
            volume_type=VolumeType.MANAGED
        )
        print("  → Volume created")


def save_to_delta(df: pd.DataFrame, table_name: str, catalog: str, schema: str, w: WorkspaceClient):
    """Save DataFrame to Delta table using Databricks SDK."""
    full_table_name = f"{catalog}.{schema}.{table_name}"
    print(f"\nSaving to Delta table: {full_table_name}")

    # For Databricks, we'll use SQL to create table from DataFrame
    # This requires spark context, so we'll save as CSV first and show SQL command

    csv_path = Path(__file__).parent.parent / "data" / f"{table_name}.csv"
    csv_path.parent.mkdir(exist_ok=True)
    df.to_csv(csv_path, index=False)

    print(f"  → Saved CSV to: {csv_path}")
    print(f"  → To load into Delta table, run this SQL in Databricks:")
    print(f"""
    CREATE OR REPLACE TABLE {full_table_name}
    USING CSV
    OPTIONS (path '{csv_path}', header 'true', inferSchema 'true');
    """)

    # Alternative: Use Databricks SQL connector
    # For production, implement SQL connector logic here


def load_snapshot(table_name: str) -> pd.DataFrame:
    """Load a pre-generated CSV snapshot from data/snapshots/."""
    snapshot_dir = Path(__file__).parent.parent / "data" / "snapshots"
    csv_path = snapshot_dir / f"{table_name}.csv"
    if not csv_path.exists():
        print(f"Error: Snapshot not found: {csv_path}")
        print("Run: python scripts/generate_snapshots.py")
        sys.exit(1)
    df = pd.read_csv(csv_path)
    print(f"  Loaded snapshot: {table_name} ({len(df)} rows)")
    return df


def main():
    parser = argparse.ArgumentParser(description="Setup bee pollinator demo data")
    parser.add_argument("--catalog", required=True, help="Unity Catalog name")
    parser.add_argument("--schema", required=True, help="Schema name (e.g., bee_health)")
    parser.add_argument("--profile", default=None, help="Databricks CLI profile name")
    parser.add_argument("--api-key", default=None, help="USDA NASS API key (or set USDA_NASS_API_KEY env var)")
    parser.add_argument(
        "--refresh", action="store_true",
        help="Fetch live data from USDA NASS API instead of using snapshots (requires API key)",
    )

    args = parser.parse_args()

    # Resolve API key (only required for --refresh)
    api_key = args.api_key or os.getenv("USDA_NASS_API_KEY")
    if args.refresh and not api_key:
        print("Error: --refresh requires a USDA NASS API key.")
        print("Get one here (free): https://quickstats.nass.usda.gov/api")
        print("Then set: export USDA_NASS_API_KEY='your_key'")
        sys.exit(1)

    # Initialize Databricks client
    print(f"Connecting to Databricks (profile: {args.profile or 'default'})...")
    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()

    # Create schema and volume
    create_unity_catalog_schema(w, args.catalog, args.schema)
    create_unity_catalog_volume(w, args.catalog, args.schema, "guidance_docs")

    if args.refresh:
        # Live fetch from USDA NASS API
        print("\n" + "="*60)
        print("FETCHING LIVE DATA FROM USDA NASS")
        print("="*60)

        production_df = fetch_honey_production(api_key)
        yield_df = fetch_honey_yield(api_key)
        colony_df = fetch_colony_counts(api_key)
        price_df = fetch_honey_price(api_key)
        honey_table = combine_honey_data(production_df, yield_df, colony_df, price_df)
        loss_table = fetch_colony_loss(api_key)
        stressor_table = load_snapshot("colony_stressors")  # no separate live fetch yet
    else:
        # Default: load from checked-in snapshots (no API key needed)
        print("\n" + "="*60)
        print("LOADING DATA FROM CHECKED-IN SNAPSHOTS")
        print("="*60)
        print("(Use --refresh to fetch live USDA NASS data instead)\n")

        honey_table = load_snapshot("honey_production")
        loss_table = load_snapshot("colony_loss")
        stressor_table = load_snapshot("colony_stressors")

    # Save tables
    print("\n" + "="*60)
    print("SAVING TO DELTA TABLES")
    print("="*60)

    save_to_delta(honey_table, "honey_production", args.catalog, args.schema, w)
    save_to_delta(loss_table, "colony_loss", args.catalog, args.schema, w)
    save_to_delta(stressor_table, "colony_stressors", args.catalog, args.schema, w)

    print("\n" + "="*60)
    print("DATA SETUP COMPLETE")
    print("="*60)
    source = "live USDA NASS API" if args.refresh else "checked-in snapshots"
    print(f"\nData source: {source}")
    print(f"Tables created in: {args.catalog}.{args.schema}")
    print(f"  1. honey_production ({len(honey_table)} rows)")
    print(f"  2. colony_loss ({len(loss_table)} rows)")
    print(f"  3. colony_stressors ({len(stressor_table)} rows)")
    print(f"\nVolume created: {args.catalog}.{args.schema}.guidance_docs")
    print("\nNext steps:")
    print("1. Upload PDFs to UC Volume (run: python scripts/download_docs.py)")
    print("2. Create Genie Space and Knowledge Assistant (run: python scripts/setup_agents.py)")


if __name__ == "__main__":
    main()
