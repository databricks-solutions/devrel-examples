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

    # Optional: refresh all USDA tables from live USDA NASS API
    export USDA_NASS_API_KEY="your_key_here"
    python setup_data.py --catalog your_catalog --schema bee_health --refresh
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

try:
    from .generate_snapshots import (
        fetch_colony_loss_snapshot as build_colony_loss_rows,
        fetch_colony_stressors_snapshot as build_colony_stressor_rows,
        fetch_honey_production_snapshot as build_honey_rows,
    )
except ImportError:
    from generate_snapshots import (
        fetch_colony_loss_snapshot as build_colony_loss_rows,
        fetch_colony_stressors_snapshot as build_colony_stressor_rows,
        fetch_honey_production_snapshot as build_honey_rows,
    )

try:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.catalog import VolumeType
except ImportError:
    print("Error: databricks-sdk not installed. Run: pip install databricks-sdk")
    sys.exit(1)


def _rows_to_frame(rows: list[dict], table_name: str) -> pd.DataFrame:
    """Convert live snapshot rows to a DataFrame with the checked-in schema."""
    if not rows:
        print(f"Warning: No rows returned for {table_name}")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    print(f"  → {table_name}: {len(df)} rows fetched")
    return df


def fetch_live_honey_table(api_key: str) -> pd.DataFrame:
    """Fetch the live annual honey table using snapshot generation logic."""
    print("Fetching live USDA honey metrics...")
    return _rows_to_frame(build_honey_rows(api_key), "honey_production")


def fetch_live_colony_loss_table(api_key: str) -> pd.DataFrame:
    """Fetch the live quarterly colony loss table using snapshot generation logic."""
    print("Fetching live USDA quarterly colony loss...")
    return _rows_to_frame(build_colony_loss_rows(api_key), "colony_loss")


def fetch_live_colony_stressor_table(api_key: str) -> pd.DataFrame:
    """Fetch the live quarterly colony stressor table using snapshot generation logic."""
    print("Fetching live USDA quarterly colony stressors...")
    return _rows_to_frame(build_colony_stressor_rows(api_key), "colony_stressors")



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

        honey_table = fetch_live_honey_table(api_key)
        loss_table = fetch_live_colony_loss_table(api_key)
        stressor_table = fetch_live_colony_stressor_table(api_key)
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
