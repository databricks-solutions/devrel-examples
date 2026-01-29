# Databricks AI Newsletter

A demo project that turns Databricks update feeds into a weekly "issue" using evidence-backed Key Information Extraction.

## Architecture

**Stage A**: Per-item Key Information Extraction (KIE)
- Input: RSS feed items + fetched page content
- Output: Structured JSON with evidence snippets

**Stage B**: Weekly Issue Editor (future)
- Input: KIE outputs for a week
- Output: Markdown newsletter issue

## Current Status

✅ Local RSS ingestion pipeline (SQLite)
✅ Production deployment (Lakebase PostgreSQL) - **WORKING!**
✅ Page content fetching (20 pages fetched successfully)
✅ Dual database support with auto-detection
🚧 Agent Bricks KIE integration (stub ready)
🚧 Weekly issue generator (TODO)
🚧 Quality gates (TODO)

**Latest Success**: Full pipeline running on Lakebase with 20 items ingested, fetched, and processed. See [LAKEBASE_SUCCESS.md](LAKEBASE_SUCCESS.md) for details.

## Database Support

Works with **both** SQLite (local) and Lakebase (production):
- Auto-detects based on environment variables
- Supports `DATABASE_URL` or individual `PG*` variables
- See [LAKEBASE_SETUP.md](LAKEBASE_SETUP.md) for details

## Quick Start

### Local (SQLite)

```bash
# Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run demo
python demo.py
```

### Lakebase (PostgreSQL)

```bash
# Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure connection (see LAKEBASE_SETUP.md)
cp .env.example .env
# Edit .env with your DATABASE_URL or PG* variables

# Test connection
python scripts/test_database_url.py

# Run demo
python demo.py
```

## Data Model

1. `sources` - RSS feed sources
2. `feed_items` - Parsed RSS items
3. `page_content` - Fetched page text
4. `kie_outputs` - Extracted key information (Agent Bricks)
5. `issues` - Weekly newsletter markdown

## Project Structure

```
databricks-ai-newsletter/
├── src/
│   ├── ingest.py      # RSS feed ingestion
│   ├── fetch.py       # Page content fetching
│   ├── kie.py         # KIE extraction (Agent Bricks stub)
│   ├── issue.py       # Issue generation (TODO)
│   ├── quality.py     # Quality gates (TODO)
│   └── schema.py      # Data model definitions
├── notebooks/         # Databricks Workflows notebooks (TODO)
├── scripts/           # Utility scripts for testing
├── data/             # Local SQLite DB (local dev only)
└── tests/
```

## Databricks Deployment

See [DATABRICKS_ORCHESTRATION.md](DATABRICKS_ORCHESTRATION.md) for:
- **Job scheduling strategies** (daily ingestion + weekly newsletters)
- **Table update triggers** for event-driven workflows
- **Parameterization** and configuration best practices
- **Complete Terraform examples** for production deployment
