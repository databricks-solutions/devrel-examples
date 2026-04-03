# Databricks notebook source
"""
Load bee-pollinator snapshot CSVs into Delta tables and upload PDFs to UC Volume.

Runs as a Databricks job task within the DAB bundle. Reads CSV snapshots
and PDF documents that are deployed alongside this notebook.
"""

# COMMAND ----------

dbutils.widgets.text("catalog", "main", "Catalog")
dbutils.widgets.text("schema", "bee_pollinator", "Schema")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")

print(f"Target: {catalog}.{schema}")

# COMMAND ----------

import csv
import glob
import io
import os
import shutil

def _resolve_bundle_root():
    """Find the bundle root directory within the deployed workspace files."""
    nb_path = (
        dbutils.notebook.entry_point
        .getDbutils().notebook().getContext()
        .notebookPath().get()
    )
    # nb_path may be /Users/... or /Workspace/Users/...
    # Ensure /Workspace prefix for filesystem access (required on serverless)
    if not nb_path.startswith("/Workspace"):
        nb_path = "/Workspace" + nb_path
    # Strip last 2 components (scripts/load_data) to get bundle root
    return "/".join(nb_path.rstrip("/").split("/")[:-2])

bundle_root = _resolve_bundle_root()
snapshot_dir = f"{bundle_root}/data/snapshots"
docs_dir = f"{bundle_root}/docs"
print(f"Bundle root: {bundle_root}")
print(f"Snapshot dir: {snapshot_dir}")
print(f"Docs dir: {docs_dir}")

# COMMAND ----------

def read_workspace_csv(path):
    """Read a CSV from the workspace filesystem and return a Spark DataFrame."""
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise ValueError(f"No data in {path}")
    return spark.createDataFrame(rows)

# COMMAND ----------

# Ensure schema and volume exist
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}`")
spark.sql(f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`{schema}`.`guidance_docs`")
print(f"Schema {catalog}.{schema} ready")
print(f"Volume {catalog}.{schema}.guidance_docs ready")

# COMMAND ----------

# --- Load CSV snapshots into Delta tables ---

TABLES = ["honey_production", "colony_loss", "colony_stressors"]

for table_name in TABLES:
    csv_path = f"{snapshot_dir}/{table_name}.csv"
    print(f"\nLoading {table_name} from {csv_path}")
    try:
        df = read_workspace_csv(csv_path)
        full_name = f"`{catalog}`.`{schema}`.`{table_name}`"
        df.write.mode("overwrite").saveAsTable(full_name)
        print(f"  {table_name}: {df.count()} rows -> {full_name}")
    except Exception as e:
        print(f"  ERROR loading {table_name}: {e}")
        raise

# COMMAND ----------

# --- Upload PDFs to UC Volume ---

volume_path = f"/Volumes/{catalog}/{schema}/guidance_docs"
print(f"\nUploading PDFs to {volume_path}")

pdf_count = 0
for entry in os.listdir(docs_dir):
    if entry.lower().endswith(".pdf"):
        src = f"{docs_dir}/{entry}"
        dst = f"{volume_path}/{entry}"
        shutil.copy2(src, dst)
        size_mb = os.path.getsize(src) / (1024 * 1024)
        print(f"  {entry} ({size_mb:.1f} MB) -> {dst}")
        pdf_count += 1

print(f"  {pdf_count} PDFs uploaded")

# COMMAND ----------

print(f"\n{'='*60}")
print("DEMO DATA LOADED SUCCESSFULLY")
print(f"{'='*60}")
print(f"\nTables in {catalog}.{schema}:")
for t in TABLES:
    count = spark.sql(f"SELECT count(*) as n FROM `{catalog}`.`{schema}`.`{t}`").first().n
    print(f"  {t}: {count} rows")
print(f"\nPDFs in {volume_path}: {pdf_count} files")
print(f"\nNext: run setup_agents.py to create Genie Space and Knowledge Assistant")
