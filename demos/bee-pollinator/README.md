# Bee Colony Health & Pollinator Supervisor Demo

A conference booth-ready demonstration of Databricks Multi-Agent Supervisor pattern using bee colony health and pollination data. The supervisor intelligently routes questions between structured agricultural data (Genie) and beekeeping guidance documents (Knowledge Assistant).

## Overview

**What it demonstrates:** Multi-Agent Supervisor pattern — automatic routing between specialized agents based on request type

**Use case:** Bee colony health advisor combining:
- USDA honey production and colony loss data (2015-2025) via Genie
- 4 key beekeeping and pollinator conservation PDFs via Knowledge Assistant

**Why this pattern matters:** Enterprise data lives in both structured tables and unstructured documents. Users shouldn't need to know which system to query. Supervisor Agents solve this by routing questions automatically.

**Target audience:** Conference booth demos - quick setup (~30 min), engaging queries, professional domain

## Architecture

```
User Question
     |
     v
┌─────────────────────────┐
│  Supervisor Agent        │
│  "Bee Health Advisor"    │
│                          │
│  Routes based on         │
│  question type           │
└─────┬──────────┬─────────┘
      │          │
      v          v
┌──────────┐  ┌──────────────┐
│  Genie   │  │  Knowledge   │
│  Space   │  │  Assistant   │
│          │  │              │
│ USDA     │  │ Varroa Mgmt  │
│ Honey    │  │ Guide        │
│ Colony   │  │ USDA Reports │
│ Loss     │  │ Plant Guides │
│ Stressor │  │ IPM Docs     │
└──────────┘  └──────────────┘
```

## Routing Examples

- **Data query** → Genie
  _"Which 5 states had the highest colony loss rates in 2023?"_

- **Document question** → Knowledge Assistant
  _"What does the Varroa Management Guide recommend for monitoring mite levels?"_

- **Cross-modal** → Both agents, synthesized answer
  _"California lost 35% of colonies in 2023. What varroa management practices should California beekeepers prioritize?"_

## Data Sources

### Structured Data (3 tables, ~13,500 rows total)

1. **USDA Honey Production by State (2015-2025)**
   - Source: USDA NASS QuickStats API
   - Fields: state, year, production, yield_per_colony, colonies, price_per_lb
   - ~420 rows

2. **USDA Colony Loss / Deadout (2015-2025)**
   - Source: USDA NASS QuickStats API
   - Fields: state, year, quarter, loss_pct, loss_colonies
   - ~1,700 rows

3. **USDA Colony Stressors (2015-2025)**
   - Source: USDA NASS QuickStats API
   - Fields: state, year, quarter, stressor, pct_affected
   - Stressors: Varroa Mites, Pesticides, Disease, Pests, Other/Unknown
   - ~11,400 rows

### Documents (4 PDFs, ~140 pages total)

1. **Tools for Varroa Management** (40 pages) - Treatment protocols, IPM, monitoring
2. **USDA Pollinator Priorities Report** (50 pages) - Federal programs, conservation
3. **Supporting Pollinators in Agricultural Landscapes** (30 pages) - Farm practices, habitat
4. **Pollinator-Friendly Plants Guide** (20 pages) - Native plants, bloom times

All data is public domain from USDA sources. This product uses the NASS API but is not endorsed or certified by NASS.

## Repository Contents

### `/scripts`
- **`setup_data.py`** — Loads data into Delta tables (from snapshots by default, or live API with `--refresh`)
- **`setup_agents.py`** — Creates Genie Space and Knowledge Assistant via Databricks SDK (CLI)
- **`create_agents.py`** — Notebook wrapper for `setup_agents.py` (runs as DAB job task)
- **`load_data.py`** — Notebook that loads CSVs + uploads PDFs (runs as DAB job task)
- **`generate_snapshots.py`** — Regenerates the checked-in CSV snapshots from live NASS API
- **`download_docs.py`** — Downloads the 4 PDFs (fallback; PDFs are already vendored)

### `/docs`
- **`BOOTH_SETUP.md`** — Step-by-step deployment guide for conference booth staff
- **`DEPLOYMENT.md`** — DAB deployment reference
- **`DEMO_GUIDE.md`** — 5-minute demo flow with example queries and MLflow integration
- **`DATA_SOURCES.md`** — Data sourcing, licensing, and refresh options
- **`*.pdf`** — The 4 source PDFs (vendored in repo)

### `/data`
- **`snapshots/`** — Pre-generated CSV files checked into the repo for zero-signup deployment

## Quick Start

### Prerequisites
- Databricks workspace with Unity Catalog enabled
- Databricks CLI v0.218+ (`databricks --version`)
- A SQL Warehouse ID (serverless or provisioned)
- **No API key needed** — demo data and PDFs ship in the repo

### Setup (~15 minutes)

```bash
cd demos/bee-pollinator

# 1. Deploy the bundle
databricks bundle deploy \
  --var="catalog=your_catalog" \
  --var="warehouse_id=your_warehouse_id"

# 2. Run the setup job (loads data + creates Genie Space & Knowledge Assistant)
databricks bundle run setup_demo \
  --var="catalog=your_catalog" \
  --var="warehouse_id=your_warehouse_id"

# 3. Create Supervisor Agent manually (only step without an API)
#    → see docs/BOOTH_SETUP.md Step 5
```

That's it. Steps 1-2 load 3 Delta tables, upload 4 PDFs, create a Genie Space, and create a Knowledge Assistant — all automated. Only the Supervisor Agent must be created in the UI (no API available yet).

See `docs/DEPLOYMENT.md` for variable customization, teardown, and troubleshooting.

### Alternative: Local CLI setup

If you prefer not to use DABs, you can run the scripts directly:

```bash
python scripts/setup_data.py --catalog your_catalog --schema bee_health
python scripts/setup_agents.py --catalog your_catalog --schema bee_health --warehouse-id your_warehouse_id
```

See `docs/BOOTH_SETUP.md` for the full manual walkthrough.

## Demo Flow (5 minutes)

See `docs/DEMO_GUIDE.md` for the full booth script, but here's the overview:

1. **[0-1 min]** Introduction - "Multi-agent routing for bee colony health"
2. **[1-2 min]** Data query → Show Genie routing and SQL generation
3. **[2-3 min]** Document query → Show Knowledge Assistant retrieval
4. **[3-4 min]** Cross-modal query → The "wow" moment combining both
5. **[4-5 min]** Show MLflow traces and experiment

## Key Conference Talking Points

- ✅ **Real USDA data** - Not toy data, actual government statistics
- ✅ **30-minute setup** - Fast deployment for booth prep
- ✅ **Engaging domain** - Everyone cares about bees and honey
- ✅ **Clear business value** - Agricultural economics + conservation
- ✅ **Professional queries** - Not just "show me data" - actionable insights

## Pattern Applications

This isn't bee-specific. Same architecture works for:
- **Customer support** — ticket data + knowledge base docs
- **Financial analysis** — market data + regulatory filings
- **Healthcare** — patient records + clinical guidelines
- **Supply chain** — logistics data + compliance documents
- **Any domain with structured data + unstructured documents**

## License

Demo materials and documentation are provided as examples. Data sources are public domain USDA datasets. PDF documents retain their original licenses (typically public domain or CC-BY for USDA publications).

## Support

For questions or issues with this demo:
- Check `docs/BOOTH_SETUP.md` for troubleshooting
- Review Databricks Supervisor Agent docs: https://docs.databricks.com/en/generative-ai/agent-bricks/multi-agent-supervisor
- File issues in this repository
