---
name: drone-swarm-4d
description: Deploy the drone swarm 4D bundle (a person filmed by two or three small drones and rebuilt as a 4D point cloud, loaded from Hugging Face into Unity Catalog, with a Databricks App that plays the 4D person, the drones' cameras and their videos in sync), open the App, and rebuild one moment yourself with Pi3X on serverless GPU. Use when deploying, checking or tearing down this example, querying its frames, telemetry or control-loop tables, or running the rebuild.
---

# Drone swarm 4D: deploy, explore, rebuild a moment

The bundle in this folder downloads the public dataset `nick-karpov/drone-swarm-4d` into a Unity Catalog volume, writes four Delta tables and deploys a viewer App. Read [`README.md`](README.md) for the story and [`data/README.md`](data/README.md) for the layout before reasoning about the data.

## 1. Check the prerequisites

- `databricks --version` is 1.3.0 or later, and the CLI is authenticated to the target workspace.
- The workspace has Unity Catalog, serverless jobs and Databricks Apps; serverless compute can reach huggingface.co.
- Ask the user for an existing catalog where they can create a schema. Never guess it.

## 2. Deploy in three steps

From this folder:

```bash
export BUNDLE_VAR_catalog=<catalog>
databricks bundle validate
databricks bundle deploy              # schema, volume release_files, job load_release, App drone-swarm-4d
databricks bundle run load_release    # Hugging Face -> volume (sha256-checked) -> clips, frames, telemetry, controls
databricks bundle run viewer          # deploys and starts the App; prints its URL
```

- The load job fails loudly if any file misses its sha256 in `manifest.json`; re-run it (it replaces every table).
- Check the load: `clips` has 2 rows; `frames` has one row per drone frame (about 300 per drone for clip1, 240 for walk_4k); `telemetry` and `controls` hold every sample of their streams.
- To load from a volume folder instead of Hugging Face: `databricks bundle run load_release --params source_dir=/Volumes/<catalog>/<schema>/<volume>/<folder>`.

## 3. Open the App

`bundle run viewer` prints the URL; it is also under *Compute → Apps → drone-swarm-4d*. Pick a clip, press play: the 4D person, each drone's frustum and every drone's video follow one timeline. *Orbit* turns the view round the person; *Follow* keeps the person centred.

The App reads the volume through the Files API as its service principal, which the bundle grants `READ VOLUME` on `release_files`. If the App shows no clips, check that the load job finished (the release must be in `/Volumes/<catalog>/<schema>/release_files/release/`).

Rules when answering from the tables:
- `t_s` is seconds from slice 0 on one clock, shared by `frames`, `telemetry`, `controls` and the slices.
- `telemetry` and `controls` are sparse: filter on `stream` and read only that stream's `<stream>_<field>` columns.
- Poses (`frames.cam_to_world`, `cameras.json`) and the clouds are in the clip frame: metres, z up, origin on the floor under the person at slice 0. Telemetry positions (`cam_odom_cam_x_m`, `control_reference_at`) are in other local frames, not the clip frame.

## 4. Rebuild one moment (serverless GPU)

Follow [`guide/REBUILD_A_MOMENT.md`](guide/REBUILD_A_MOMENT.md). In short, from `rebuild/`, after filling the placeholders in `job.yaml` (catalog, schema, clip, time):

```bash
cd rebuild
air run --file job.yaml -p <profile>     # or: databricks air run --file job.yaml -p <profile>
```

- The job writes `/Volumes/<catalog>/<schema>/release_files/rebuilds/<clip>/sNNN.bin` and `sNNN.json`; reload the App and switch to *Your rebuild* or *Both*.
- Read `sNNN.json`: `comparison.chamfer_cm`, the point counts, and `alignment.camera_rotation_error_deg` / `camera_centre_error_cm` (how far Pi3X moved the cameras it was given).
- The job prints a start marker, one line per stage, and exits non-zero on any error. Check the run's output before re-running.

## 5. Tear down

```bash
databricks bundle destroy
```

If the schema delete is refused because it still holds tables, run `DROP SCHEMA <catalog>.drone_swarm_4d CASCADE` and then `destroy` again. Confirm with the user before dropping anything.
