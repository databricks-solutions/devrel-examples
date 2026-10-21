---
name: quadcopter-telemetry-genie
description: Deploy the quadcopter flight-telemetry bundle (13 anonymised flights of a small consumer quadcopter, as Delta tables in Unity Catalog, with a Genie space over them) and explore the data with Genie, including deriving a finer wind direction from the aircraft's tilt. Use when deploying, checking or tearing down this example, or when answering questions about its flights, wind and dock landings.
---

# Quadcopter flight telemetry: deploy and explore with Genie

The bundle in this folder loads a static release (`data/*.parquet`) into Unity Catalog and creates a Genie space over the raw tables. Read [`README.md`](README.md) for the story and [`data/README.md`](data/README.md) for every column, frame and sign before reasoning about the data.

## 1. Check the prerequisites

- `databricks --version` is 1.3.0 or later (the `genie_spaces` resource and the direct engine need it), and the CLI is authenticated to the target workspace.
- Ask the user for an existing catalog where they can create a schema, and a Pro or serverless SQL warehouse id (`databricks warehouses list` shows candidates). Never guess either.

## 2. Deploy in three steps

From this folder:

```bash
export BUNDLE_VAR_catalog=<catalog> BUNDLE_VAR_warehouse_id=<warehouse_id>
databricks bundle validate
databricks bundle deploy              # first time: expected to fail at the Genie space ("Table ... does not exist")
databricks bundle run load_release0   # writes flights, telemetry, landings, blended_wind_reference
databricks bundle deploy              # creates the Genie space
```

- The first deploy's failure at the Genie space is expected: the space needs its tables, and only the job creates them. Anything else failing in that deploy is a real error.
- Check the load: the job's notebook output (or `SELECT COUNT(*)` on each table) must give flights 13, telemetry 33,851, landings 6, blended_wind_reference 33,851.

## 3. Explore with Genie

Open Genie, pick *Quadcopter Flight Telemetry*, and ask each question in a fresh conversation. Compare with the reference answers; Genie writes its own SQL, so small differences are normal.

| Question | Reference |
|---|---|
| Which flight was the gustiest? Use the biggest short gust above the flight's average wind. | The `day_2` automated-manoeuvres flight: 3 s gust 1.75 m/s above a 3.00 m/s mean |
| How many of the dock landings seated? | 4 of 6 |
| The flight controller only gives wind direction in 45° steps. Using the drone's tilt during steady flight, estimate a finer wind direction for each flight. | Windiest flights: from about 13° to 23°, between the N and NE sectors |

Rules when answering from these tables:
- `blended_wind_reference` is a reference answer and is not in the Genie space on purpose. Use it only to compare a derived direction, in the SQL editor.
- The wind estimate is meaningful only clear of the ground: ignore it on the ground, at take-off, at touchdown and at hand catches, and treat it as noise for the dock flights (they hover under about 1 m).
- Wind directions are where the wind blows *from*, clockwise from north, and wrap at 360: average them as vectors, never arithmetically.

For the full tilt derivation, step by step with the SQL Genie should reach, follow [`guide/DERIVE_BLENDED_WIND.md`](guide/DERIVE_BLENDED_WIND.md).

## 4. Tear down

```bash
databricks bundle destroy
```

If the schema delete is refused because it still holds tables, run `DROP SCHEMA <catalog>.quadcopter_flights CASCADE` and then `destroy` again. Confirm with the user before dropping anything.
