# Quadcopter Flight Telemetry with Genie

Real flight telemetry from a small drone, in Unity Catalog, with a Genie space that answers questions about it in plain language.

## The story

We fly a sub-250 g consumer quadcopter. Its flight controller is a closed, commercial black box: you command sticks, not motors, and it reports what it measures (pose, velocity, attitude, battery and its own wind estimate). We fly it from our own ground-control software, and each flight's telemetry streams through Zerobus Ingest into Delta tables while the aircraft is in the air.

Over those tables, a Genie space answers questions straight from the raw telemetry: which flight was the gustiest, how many dock landings seated, which way the wind was blowing. The space gets domain notes (units, frames, what the flight controller reports), not formulas or example SQL, so Genie works the answers out itself.

**The blended wind.** The flight controller estimates the wind speed well, but gives its direction only in 45° steps (N, NE, E, ...). In a wind from about 20° it flips between N and NE several times a minute. The airframe carries the missing information: in steady flight a multirotor tilts into the wind so that thrust balances drag. Read that tilt back through a drag model and you get the air-relative velocity; ground velocity minus air velocity is the wind. Kept inside the controller's own 45° sector, that gives a finer direction. The dataset ships this "blended" direction as a reference table, and [the guide](guide/DERIVE_BLENDED_WIND.md) rebuilds it step by step in Genie.

**What this example ships.** A static, anonymised release of 13 flights: 7 wind flights and 6 autonomous landings on a charging dock. The bundle loads it into Unity Catalog once and creates the Genie space. **The live Zerobus Ingest path from a flying aircraft is not included.**

## Folder contents

| Path | What it is |
|---|---|
| `databricks.yml` | The bundle: engine, variables, target |
| `resources/data.yml` | Schema, volume and the load job |
| `resources/genie.yml` | The Genie space, as a native `genie_spaces` bundle resource |
| `src/load_release.py` | The load job's notebook: parquet → volume → Delta tables with table and column comments |
| `data/` | The release: four parquet files (about 0.7 MB) and [`data/README.md`](data/README.md), the full data description |
| `guide/DERIVE_BLENDED_WIND.md` | Derive the blended wind direction yourself, in Genie, and compare it with the reference |
| `SKILL.md` | A short agent skill: deploy the bundle and explore the data with Genie |

`SKILL.md` has skill front matter, so an AI coding agent can use it directly: for Claude Code, copy this folder to `.claude/skills/quadcopter-telemetry-genie/` in your project (or `~/.claude/skills/`); for other agents, add it as a skill or instructions file.

## The tables

| Table | Rows | What |
|---|---|---|
| `flights` | 13 | One row per flight: site, day, kind (`manual`, `automated_manoeuvres`, `system_identification`, `autonomous_dock_cycle`), duration, airborne time, how it ended |
| `telemetry` | 33,851 | One row per flight-controller sample (about 10 Hz): position relative to take-off, velocity, pitch, roll, heading, the flight controller's wind speed and 45° direction, battery, commanded sticks |
| `landings` | 6 | One row per dock landing attempt: error, heading error and speed at the commit, low-hold time, retries, and the dock's own verdict (`seated` or `not_seated`) |
| `blended_wind_reference` | 33,851 | The blended wind for each telemetry sample. A reference answer: loaded, but **not** given to the Genie space |

Units are in the column names (`_m`, `_mps`, `_deg`, `_s`, `_cm`, `_cmps`). Positions are in a local frame about the take-off point (x north, y east, z up); time is seconds since each flight's first sample. Ids are keyed hashes, and there are no coordinates, dates, video or device identifiers. See [`data/README.md`](data/README.md) for every column, the frames and signs, the anonymisation, the blended-wind method, the gust metric and the known limits.

## Prerequisites

- **Databricks CLI 1.3.0 or later** (the `genie_spaces` resource and the direct deployment engine need it), authenticated to your workspace (`databricks auth login`). See [Install or update the Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install).
- A workspace with **Unity Catalog** and **serverless compute for jobs**.
- An existing **catalog** on which you have `USE CATALOG` and `CREATE SCHEMA`. The bundle creates a schema; it does not create a catalog.
- A **Pro or serverless SQL warehouse** you can use (`CAN USE`), for the Genie space. Find its ID under *SQL Warehouses → (warehouse) → Overview*, or with `databricks warehouses list`.
- **Genie** enabled for the workspace (the Databricks SQL entitlement, and the partner-powered AI features setting on for the account).

## Deploy

From this folder, set the two required variables once:

```bash
cd demos/quadcopter-flight-telemetry
export BUNDLE_VAR_catalog=<your_catalog> BUNDLE_VAR_warehouse_id=<warehouse_id>
databricks bundle validate
```

Then deploy, load, and deploy again:

```bash
databricks bundle deploy              # 1. syncs the files, creates the schema, volume and job; stops at the Genie space
databricks bundle run load_release0   # 2. loads the four parquet files into Delta tables
databricks bundle deploy              # 3. creates the Genie space, now that its tables exist
```

**Why two deploys.** The Genie space needs its tables to exist, and the tables are written by the load job, which runs after a deploy. On a real workspace the first deploy fails at the Genie space with `PERMISSION_DENIED` ("Table ... does not exist"); everything else is created. Run the job, then deploy again: the deploy is idempotent and creates only what is missing. Later deploys go through in one step.

Then open **Genie** in the workspace sidebar and pick *Quadcopter Flight Telemetry*.

| Variable | Default | Meaning |
|---|---|---|
| `catalog` | (required) | Existing catalog to create the schema in |
| `schema` | `quadcopter_flights` | Schema to create |
| `warehouse_id` | (required) | Pro or serverless SQL warehouse for the Genie space |

You can also pass them on each command, e.g. `--var="catalog=<your_catalog>" --var="warehouse_id=<warehouse_id>"`.

**What gets created:** the schema; a managed volume `release_files` holding the parquet files as published; the job *Load quadcopter release 0* (one serverless notebook task, safe to re-run: it replaces every table); the four Delta tables, with table and column comments; and the Genie space over `flights`, `telemetry` and `landings`.

By default the job reads the parquet files from the bundle's synced copy (`${workspace.file_path}/data`). To load them from a volume folder instead, upload the four files there and run `databricks bundle run load_release0 --params source_dir=/Volumes/<catalog>/<schema>/<volume>/<folder>`.

## Questions to ask Genie

Start a new conversation for each question:

- *Which flight was the gustiest? Use the biggest short gust above the flight's average wind.*
- *How many of the dock landings seated?*
- *The flight controller only gives wind direction in 45° steps. Using the drone's tilt during steady flight, estimate a finer wind direction for each flight.*
- *Which way was the wind blowing on each flight?*

Reference answers, to check Genie against (Genie writes its own SQL, so its numbers vary a little from run to run):

| Question | Reference |
|---|---|
| Gustiest flight | The `day_2` automated-manoeuvres flight: a 3 s gust 1.75 m/s above its 3.00 m/s mean wind (the gust metric is defined in [`data/README.md`](data/README.md#gust-metric)) |
| Dock landings seated | 4 of 6 |
| Finer wind direction | On the windiest flights the wind comes from about 13° to 23°, between the controller's N and NE sectors |

## Derive the blended wind yourself

[`guide/DERIVE_BLENDED_WIND.md`](guide/DERIVE_BLENDED_WIND.md) walks through the blended wind in five prompts, one stage each, in one Genie conversation: steady samples, the wind the tilt implies, smoothing, the clamp to the controller's sector, and a comparison with `blended_wind_reference`. Under each prompt is the SQL Genie should arrive at. The last step reads the reference table, which the space does not include, so it runs in the SQL editor; the complete query is at the end of the guide.

## Cost

- **Storage:** about 1 MB of parquet and Delta.
- **Job:** one short serverless notebook run per load, typically a minute or two. Nothing is scheduled.
- **Genie:** queries run on your SQL warehouse. A serverless warehouse starts on the first question and stops after its auto-stop time; the tables are small, so the cost is mostly the warehouse's minimum running time.
- No clusters, pipelines, schedules or serving endpoints are created.

## Tear down

With the same variables set:

```bash
databricks bundle destroy
```

This removes the Genie space, the job, the volume (with its files) and the schema. The tables are not bundle resources but live in the schema; if the schema delete is refused because it still holds tables, drop it yourself and run `destroy` again to clear the bundle's state:

```sql
DROP SCHEMA <your_catalog>.quadcopter_flights CASCADE;
```

## What was tested

- On a Databricks workspace with CLI 1.6.0: `bundle validate`, `deploy` (deploy, run, deploy as above, and updating the Genie space in place) and `run`; the four tables load with the expected row counts (13, 33,851, 6, 33,851); Genie's answers to the first two questions match the reference; the guide's complete query matches the reference table on a SQL warehouse.
- That run used an earlier folder layout, with `data/` beside the bundle folder. In this layout `data/` is inside the bundle root and synced to the same workspace path (`${workspace.file_path}/data`); this layout has not been deployed yet.
- Not tested: `bundle destroy`; the guide's step-by-step prompts in Genie (its SQL was run, the prompt wording was not).

## Licences

- Code (the bundle, the notebook and the guide's SQL): the repository's [LICENSE](../../LICENSE.txt).
- Data (`data/`): [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).

## How to get help

Databricks support doesn't cover this content. For questions or bugs, please open a GitHub issue and the team will help on a best effort basis.
