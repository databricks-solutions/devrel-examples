# Bee Pollinator Demo — DAB Deployment Guide

This document describes deploying the bee-pollinator demo using
**Databricks Asset Bundles (DABs)**. A single `bundle deploy` +
`bundle run` creates everything except the Supervisor Agent (which
has no API yet).

---

## What the bundle automates

| Step | Resource | How |
|------|----------|-----|
| Delta tables (3) | `honey_production`, `colony_loss`, `colony_stressors` | Job task `load_data` loads vendored CSVs |
| UC Volume + PDFs | `guidance_docs` with 4 PDFs | Job task `load_data` creates volume via SQL and copies PDFs |
| Genie Space | `USDA Bee Health Data` | Job task `create_agents` uses Databricks SDK |
| Knowledge Assistant | `Bee Health Documents` | Job task `create_agents` uses Databricks SDK |

## What remains manual

| Step | Why |
|------|-----|
| **Supervisor Agent** | No API exists (as of March 2026). See [BOOTH_SETUP.md](BOOTH_SETUP.md) Step 5 |

---

## Prerequisites

1. **Databricks CLI** v0.218+ (`databricks --version`).
2. A CLI profile authenticated to your workspace:
   ```bash
   databricks auth login --profile your_profile
   ```
3. The workspace must have **Unity Catalog** enabled.
4. A catalog you can write to and a **SQL Warehouse ID**.

---

## Quick start

```bash
cd demos/bee-pollinator

# 1. Validate (catches config errors)
databricks bundle validate \
  --var="catalog=your_catalog" \
  --var="warehouse_id=your_warehouse_id"

# 2. Deploy job definition to workspace
databricks bundle deploy \
  --var="catalog=your_catalog" \
  --var="warehouse_id=your_warehouse_id"

# 3. Run the setup job (load data → create agents)
databricks bundle run setup_demo \
  --var="catalog=your_catalog" \
  --var="warehouse_id=your_warehouse_id"

# 4. Create Supervisor Agent manually (see BOOTH_SETUP.md Step 5)
```

Add `--profile your_profile` to each command if not using the default profile.

---

## Variables

Override defaults via `--var` flags or by editing `databricks.yml`:

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `catalog` | `main` | No | Unity Catalog catalog name |
| `schema` | `bee_pollinator` | No | Schema for demo tables |
| `warehouse_id` | — | **Yes** | SQL Warehouse ID for Genie Space |

---

## Bundle files

| File | Purpose |
|------|---------|
| `databricks.yml` | Bundle config — job, variables, targets |
| `scripts/load_data.py` | Notebook: loads CSVs → Delta tables, uploads PDFs → UC Volume |
| `scripts/create_agents.py` | Notebook: creates Genie Space + Knowledge Assistant via SDK |
| `scripts/setup_agents.py` | Python module imported by `create_agents.py` (also usable as CLI) |
| `data/snapshots/*.csv` | Real USDA NASS data (3 tables) |
| `docs/*.pdf` | Vendored PDF documents (4 files) |

The entire directory is synced to the workspace on `bundle deploy`.

---

## Job structure

The `setup_demo` job has two sequential tasks on serverless compute:

```
load_data  →  create_agents
```

- **`load_data`**: Creates schema + volume via SQL, loads 3 CSV snapshots into Delta tables, copies 4 PDFs to the UC Volume.
- **`create_agents`**: Creates a Genie Space (with table descriptions, instructions, and sample queries) and a Knowledge Assistant (with the PDF volume as knowledge source). Depends on `load_data`.

---

## Tear down

```bash
# Remove bundle-managed resources (job definition)
databricks bundle destroy

# Tables, schema, volume, and agents must be cleaned up separately:
#   - Drop schema: cascades to tables and volume
#   - Delete Genie Space and KA from the UI or via SDK
#   - Delete Supervisor Agent from the UI
```

---

## Troubleshooting

### `bundle validate` fails with auth error
```bash
databricks auth login --profile your_profile
databricks auth describe --profile your_profile
```

### `load_data` task fails reading CSVs
The notebook resolves paths relative to its workspace location. Verify the bundle deployed:
```bash
databricks workspace ls \
  "/Workspace/Users/<you>/.bundle/bee-pollinator-demo/dev/files/data/snapshots"
```

### `create_agents` task fails with "No module named knowledgeassistants"
The bundle specifies `databricks-sdk>=0.44.0` in the environment. If the version pinned by the serverless runtime is too old, try upgrading the pin in `databricks.yml`.

### `create_agents` task fails with Genie API validation errors
The Genie serialized space requires lists sorted by `id` or `identifier`. If you modify `setup_agents.py`, ensure all list payloads remain sorted.

---

## Data refresh

The checked-in snapshots contain real USDA NASS data. To refresh:

```bash
# Requires USDA_NASS_API_KEY (free signup)
USDA_NASS_API_KEY=your_key python scripts/generate_snapshots.py
```

Then redeploy and rerun:

```bash
databricks bundle deploy --var="catalog=X" --var="warehouse_id=Y"
databricks bundle run setup_demo --var="catalog=X" --var="warehouse_id=Y"
```
