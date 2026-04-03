# Databricks notebook source
"""
Create Genie Space and Knowledge Assistant for the bee-pollinator demo.

Runs as a Databricks job task within the DAB bundle. Uses the Databricks SDK
(pre-installed on serverless) with automatic workspace authentication.

Imports core logic from setup_agents.py (deployed alongside this notebook).
"""

# COMMAND ----------

dbutils.widgets.text("catalog", "main", "Catalog")
dbutils.widgets.text("schema", "bee_pollinator", "Schema")
dbutils.widgets.text("warehouse_id", "", "SQL Warehouse ID")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
warehouse_id = dbutils.widgets.get("warehouse_id")

if not warehouse_id:
    raise ValueError("warehouse_id parameter is required")

print(f"Catalog: {catalog}")
print(f"Schema: {schema}")
print(f"Warehouse ID: {warehouse_id}")

# COMMAND ----------

import importlib
import sys

# The bundle deploys setup_agents.py alongside this notebook.
# Add the scripts directory to sys.path so we can import it.
def _resolve_scripts_dir():
    nb_path = (
        dbutils.notebook.entry_point
        .getDbutils().notebook().getContext()
        .notebookPath().get()
    )
    if not nb_path.startswith("/Workspace"):
        nb_path = "/Workspace" + nb_path
    # Strip the notebook name to get the scripts directory
    return "/".join(nb_path.rstrip("/").split("/")[:-1])

scripts_dir = _resolve_scripts_dir()
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

import setup_agents
importlib.reload(setup_agents)  # Ensure fresh import if re-running

print(f"Loaded setup_agents from: {scripts_dir}")

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

print("=" * 60)
print("CREATING AGENTS FOR BEE POLLINATOR DEMO")
print("=" * 60)

# COMMAND ----------

# --- Create Genie Space ---

genie_id = setup_agents.create_genie_space(
    w, catalog, schema, warehouse_id, "USDA Bee Health Data"
)

# COMMAND ----------

# --- Create Knowledge Assistant ---

ka_id = setup_agents.create_knowledge_assistant(
    w, catalog, schema, "guidance_docs", "Bee Health Documents"
)

# COMMAND ----------

# --- Print Supervisor Agent instructions (manual step) ---

setup_agents.print_supervisor_instructions("USDA Bee Health Data", "Bee Health Documents")

# COMMAND ----------

print(f"\n{'=' * 60}")
print("AGENT SETUP COMPLETE")
print(f"{'=' * 60}")
print(f"\nGenie Space: {genie_id}")
print(f"Knowledge Assistant: {ka_id}")
print("\nNext: Create Supervisor Agent manually (see instructions above)")
