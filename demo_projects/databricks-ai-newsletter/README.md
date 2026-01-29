# Databricks AI Newsletter

A demo project that turns Databricks update feeds into a weekly newsletter using Lakebase and evidence-backed Key Information Extraction.

## Architecture

**Pipeline:**
1. **RSS Ingestion** - Fetch and parse Databricks docs RSS feed
2. **Content Extraction** - Fetch and extract text from documentation pages
3. **Key Information Extraction** - Extract structured insights with evidence snippets (Agent Bricks)
4. **Issue Generation** - Create weekly newsletter (TODO)

**Storage:** Lakebase (PostgreSQL) with OAuth token authentication

## Quick Start

### 1. Prerequisites

- Databricks workspace with Lakebase Autoscaling enabled
- Databricks CLI installed and authenticated

### 2. Find Your Lakebase Configuration

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Discover your Lakebase endpoint configuration
python scripts/discover_lakebase.py
```

This will output values like:
```
lakebase_endpoint: projects/abc123/branches/main/endpoints/ep-123
pghost: ep-123.database.us-west-2.cloud.databricks.com
pgdatabase: databricks_postgres
```

### 3. Configure databricks.yml

Update the `variables` section in `databricks.yml`:

```yaml
variables:
  lakebase_endpoint:
    default: projects/YOUR_PROJECT_ID/branches/YOUR_BRANCH/endpoints/YOUR_ENDPOINT
  pghost:
    default: your-endpoint.database.region.cloud.databricks.com
  pgdatabase:
    default: databricks_postgres
```

Also update:
```yaml
workspace:
  host: https://your-workspace.cloud.databricks.com
```

### 4. Deploy to Databricks

```bash
# Validate configuration
databricks bundle validate

# Deploy
databricks bundle deploy -t dev

# Test run
databricks bundle run daily_ingest_job -t dev
```

## Authentication

Uses **OAuth tokens** generated automatically via Databricks SDK:
- No secrets to manage
- Tokens auto-refresh each job run
- Uses your Databricks identity
- Expires after 1 hour (jobs finish in ~5 minutes)

The notebook automatically:
1. Reads configuration from job parameters
2. Generates fresh OAuth token via `w.postgres.generate_database_credential()`
3. Connects to Lakebase using token

## Data Model

Lakebase tables:
1. `sources` - RSS feed sources (Databricks docs)
2. `feed_items` - Parsed RSS items with metadata
3. `page_content` - Fetched documentation page text
4. `kie_outputs` - Extracted key information with evidence
5. `issues` - Generated weekly newsletters (TODO)

## Project Structure

```
databricks-ai-newsletter/
├── databricks.yml           # Databricks Asset Bundle config
├── notebooks/
│   └── daily_ingest.ipynb  # Main pipeline notebook
├── src/
│   ├── schema.py           # Database schema (SQLite + PostgreSQL)
│   ├── ingest.py           # RSS feed ingestion
│   ├── fetch.py            # Page content fetching
│   └── kie.py              # KIE extraction (stub for Agent Bricks)
├── scripts/
│   └── discover_lakebase.py # Auto-discover Lakebase config
└── requirements.txt
```

## Configuration

All configuration via `databricks.yml` variables - no hardcoded credentials:

- **lakebase_endpoint** - Full path to your Lakebase endpoint
- **pghost** - PostgreSQL hostname
- **pgdatabase** - Database name
- **workspace.host** - Your Databricks workspace URL

Environment-specific overrides supported (dev/prod).

## Job Schedule

Default: Daily at 2 AM Pacific (configurable in `databricks.yml`)

```yaml
schedule:
  quartz_cron_expression: "0 0 2 * * ?"
  timezone_id: "America/Los_Angeles"
  pause_status: PAUSED  # Change to UNPAUSED to enable
```

## Development

The source modules (`src/`) support both SQLite (local testing) and Lakebase (production):

```python
from src.schema import get_connection
conn = get_connection()  # Auto-detects SQLite or Lakebase
```

## Next Steps

1. Integrate Agent Bricks for real KIE extraction
2. Build weekly issue generator
3. Add quality gates
4. Set up table update triggers for weekly newsletter generation
