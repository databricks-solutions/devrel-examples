# Bee Pollinator Demo — Data Sources

This product uses the NASS API but is not endorsed or certified by NASS.

## Data Overview

The demo uses three structured tables (all real USDA NASS data) and four PDF documents (~140 pages).

| Table | Rows | Size | Source | Status |
|-------|------|------|--------|--------|
| `honey_production` | ~420 | ~15 KB | USDA NASS QuickStats API | Real data, checked-in snapshot |
| `colony_loss` | ~1,700 | ~45 KB | USDA NASS QuickStats API | Real data, checked-in snapshot |
| `colony_stressors` | ~11,400 | ~404 KB | USDA NASS QuickStats API | Real data, checked-in snapshot |

## Recommended Default: Checked-In Snapshots (Zero Signup)

**The demo ships with pre-generated CSV snapshots in `data/snapshots/`.** Operators can deploy the full demo without any API key or external data fetch.

### Why This Works

1. **Data is tiny** — All three tables total ~465 KB as CSV. Git handles this trivially.
2. **USDA data is public domain** — U.S. government works (17 U.S.C. § 105) are not copyrightable. USDA NASS data is explicitly listed as CC0/public domain on Data.gov.
3. **All data is real** — All three tables contain actual USDA NASS data fetched from the QuickStats API.
4. **Demo purpose is architecture, not data freshness** — The demo showcases the Supervisor Agent pattern. Having real data is important, but it doesn't need to be updated daily.

### Data Attribution

> Source: USDA National Agricultural Statistics Service (NASS), QuickStats API.
> https://quickstats.nass.usda.gov/
> USDA NASS data is public domain (U.S. Government Work, CC0).

## Operator Experience

### Default (Zero Signup)

```bash
# No API key needed — snapshots are already in the repo
python scripts/setup_data.py --catalog my_catalog --schema bee_health
```

The script loads CSVs from `data/snapshots/` and creates Delta tables in Unity Catalog.

### Optional: Refresh with Live USDA Data

```bash
# Get a free API key (5-minute signup): https://quickstats.nass.usda.gov/api
export USDA_NASS_API_KEY="your_key"
python scripts/setup_data.py --catalog my_catalog --schema bee_health --refresh
```

With `--refresh`, the script fetches live data from the USDA NASS QuickStats API and updates both tables with current statistics.

### Regenerate Snapshots

```bash
# Fetch fresh data and update the checked-in CSVs
USDA_NASS_API_KEY=your_key python scripts/generate_snapshots.py
```

## NASS API Query Details

| Table | `statisticcat_desc` | Notes |
|-------|-------------------|-------|
| `honey_production` | `PRODUCTION` (LB, LB/COLONY), `INVENTORY`, `PRICE RECEIVED` | Combined from 4 sub-queries |
| `colony_loss` | `LOSS, DEADOUT` | Both PCT OF COLONIES and absolute COLONIES counts, quarterly |
| `colony_stressors` | `INVENTORY` (PCT OF COLONIES) | % affected by varroa, pesticides, disease, pests, other, unknown |

## USDA Data Access Options (No-Auth)

For reference, USDA NASS data can also be accessed without an API key via:

1. **Quick Stats Web UI**: https://quickstats.nass.usda.gov/ — interactive query builder with CSV export
2. **Bulk Downloads**: ftp://ftp.nass.usda.gov/quickstats/ — daily full-database dumps (~1 GB compressed)
3. **Data.gov**: https://catalog.data.gov/dataset/quick-stats-agricultural-database-api

The API key is only needed for programmatic REST access. For this demo, the checked-in snapshots eliminate the need for any of these paths.
