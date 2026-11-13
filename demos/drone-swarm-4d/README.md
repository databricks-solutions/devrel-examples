# Drone Swarm 4D

A person filmed by a small swarm of drones and rebuilt in 4D, in Unity Catalog, with a Databricks App to explore it and a serverless GPU job that rebuilds one moment yourself.

## The story

Two or three small consumer drones followed one person outdoors and filmed him from 2–5 m away, from different sides at once. There was no rig, no studio and no markers: the swarm was flown by our own ground-control software, which also recorded every drone's telemetry and the swarm's control loop.

Every video frame carries the drone's own clock, so all drones, all frames and all telemetry share one time base. At each instant (a *slice*, 29.97 per second) the drones' synchronised views are solved jointly with Pi3X, a feed-forward multi-view geometry model, put into a metric frame through the drones' poses, merged and smoothed in time. The result is a time-varying, coloured point cloud of the person: 40–110 thousand points per slice, with every drone's camera pose and its person-masked video alongside.

**What this example ships.** The release lives on Hugging Face as [`nick-karpov/drone-swarm-4d`](https://huggingface.co/datasets/nick-karpov/drone-swarm-4d): two clips, the person only (every video is masked to the person, and the clouds hold only the person). The bundle downloads it into a Unity Catalog volume, checks every file, loads the frames, telemetry and control loop into Delta tables, and deploys the **4D viewer App**: the person in 3D with each drone's camera frustum, every drone's video underneath, and one timeline that drives them all.

**Rebuild a moment.** [The guide](guide/REBUILD_A_MOMENT.md) runs Pi3X yourself on serverless GPU for one instant: it reads each drone's frame, mask and pose from the volume, rebuilds the person, aligns the result to the release with the published poses and writes a cloud the App shows next to the release, with a Chamfer comparison.

<!-- HERO GIF: the App on clip1_three_drones, an orbit round the person with the three drone frustums.
     Record it with tests/record_hero.mjs, then add it here, e.g. ![The 4D viewer](guide/hero.gif) -->

## Folder contents

| Path | What it is |
|---|---|
| `databricks.yml` | The bundle: engine, variables, target |
| `resources/data.yml` | Schema, volume and the load job |
| `resources/app.yml` | The App, with read access to the volume |
| `src/load_release.py` | The load job's notebook: Hugging Face → volume (sha256-checked) → Delta tables with table and column comments |
| `app/` | The App: a small FastAPI server (`app.py`) and the three.js viewer (`static/index.html`) |
| `rebuild/` | The serverless GPU job for one moment: `job.yaml`, `entry.sh`, `rebuild_moment.py` |
| `guide/REBUILD_A_MOMENT.md` | Rebuild one moment with Pi3X on serverless GPU and compare it with the release |
| `data/README.md` | Where the data lives and how it is laid out |
| `tests/` | Local checks: a synthetic release in the same layout, a PySpark run of the load notebook, headless screenshots of the App, the hero recording |
| `SKILL.md` | A short agent skill: deploy, open the App, run the rebuild |

`SKILL.md` has skill front matter, so an AI coding agent can use it directly: for Claude Code, copy this folder to `.claude/skills/drone-swarm-4d/` in your project (or `~/.claude/skills/`); for other agents, add it as a skill or instructions file.

## The tables

| Table | Rows | What |
|---|---|---|
| `clips` | 2 | One row per clip: drones, duration, frame rate, slice times, frame of reference, per-drone intrinsics, the volume folder and `clip.json` as published |
| `frames` | one per drone video frame | When each frame was taken, the camera-to-world pose (16 numbers, row-major, OpenCV camera), the camera centre, intrinsics, and the path of its video |
| `telemetry` | one per sample | What each drone reported: camera odometry, attitude, flight-controller state, radar, range, exposure, battery, motors, temperatures, wind, RC sticks, radio link, keyframe markers |
| `controls` | one per sample | The swarm's control loop: the person detector that drives the follow, the follow references, the controller's stick intents and ticks, the stick frames sent to each drone, link traffic and events |

`telemetry` and `controls` come from one sparse table in the release (one struct column per stream). Each stream's fields are flattened to `<stream>_<field>` columns, and each row sets only its own stream's columns: for example `SELECT drone, t_s, fc_state_alt_m, fc_state_heading_deg FROM telemetry WHERE stream = 'fc_state'`. Every table and column has a comment; `t_s` is seconds from slice 0 on one clock across all tables. See [`data/README.md`](data/README.md) and the [dataset card](https://huggingface.co/datasets/nick-karpov/drone-swarm-4d) for every file and stream.

## Prerequisites

- **Databricks CLI 1.3.0 or later**, authenticated to your workspace (`databricks auth login`). See [Install or update the Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install).
- A workspace with **Unity Catalog**, **serverless compute for jobs** and **Databricks Apps**.
- An existing **catalog** on which you have `USE CATALOG` and `CREATE SCHEMA`. The bundle creates a schema; it does not create a catalog.
- Outbound internet from serverless compute, to download the release from Hugging Face (public, no token).
- For the GPU hands-on: **serverless GPU compute (AI Runtime)** and the `air` CLI (or `databricks air`); see [the guide](guide/REBUILD_A_MOMENT.md).

## Deploy

From this folder, set the catalog once:

```bash
cd demos/drone-swarm-4d
export BUNDLE_VAR_catalog=<your_catalog>
databricks bundle validate
```

Then deploy, load and start the App:

```bash
databricks bundle deploy              # 1. schema, volume, load job and the App
databricks bundle run load_release    # 2. downloads the release into the volume, checks it, writes the tables
databricks bundle run viewer          # 3. deploys and starts the App
```

Then open **Compute → Apps → drone-swarm-4d** (or the URL `bundle run viewer` prints), pick a clip and press play.

| Variable | Default | Meaning |
|---|---|---|
| `catalog` | (required) | Existing catalog to create the schema in |
| `schema` | `drone_swarm_4d` | Schema to create |

You can also pass them on each command, e.g. `--var="catalog=<your_catalog>"`.

**What gets created:** the schema; a managed volume `release_files` holding the release as published (`release/`) and your rebuilt moments (`rebuilds/`); the job *Load drone swarm 4D release* (one serverless notebook task, safe to re-run: it replaces every table); the four Delta tables, with table and column comments; and the App *drone-swarm-4d*, whose service principal gets `READ VOLUME` on `release_files`.

By default the job downloads the release from Hugging Face (`hf_repo`, `hf_revision`). To load it from a volume folder instead, put the release there (the folder holding `manifest.json` and `clips/`) and run `databricks bundle run load_release --params source_dir=/Volumes/<catalog>/<schema>/<volume>/<folder>`.

## The App

- **Top:** the two clips.
- **Centre:** the person in 3D, with orbit and zoom, and each drone's camera as a wire frustum built from its intrinsics, placed from `cameras.json` at the current slice. *Orbit* turns the view slowly round the person while time plays; *Follow* keeps the person centred; *Reset* frames the scene again.
- **Below:** every drone's person-masked video.
- **Bottom:** one play/pause and timeline that drive the slice, the frustums and all videos together.
- **Your rebuild:** when the rebuild job has written a moment for the clip, *Release / Your rebuild / Both* switches between the published slice, yours, and the two overlaid, with the Chamfer distance between them.

How it reads the data: `app/app.py` serves the viewer and streams the release files from the volume through the Files API (`WorkspaceClient().files`, with HTTP range requests forwarded for video seeking), as the App's service principal. The bundle declares the volume as an App resource with `READ_VOLUME`, which grants that principal read access. To run it on your laptop against a local copy of the release:

```bash
pip install -r app/requirements.txt
DRONE4D_LOCAL_DIR=/path/to/drone-swarm-4d python app/app.py      # then open http://localhost:8000
```

## Rebuild one moment

[`guide/REBUILD_A_MOMENT.md`](guide/REBUILD_A_MOMENT.md) runs `rebuild/` as one serverless GPU job: pick a time, and the job writes `rebuilds/<clip>/sNNN.bin` and `sNNN.json` to the volume. Refresh the App to see it.

## Cost

- **Storage:** the release is a few hundred MB in all (videos, masks and about 540 point clouds), plus small Delta tables.
- **Load job:** one serverless notebook run, a few minutes, mostly the download and the sha256 check. Nothing is scheduled.
- **App:** billed while it runs; stop it under *Compute → Apps* when you are done.
- **Rebuild:** one serverless GPU job on a single A10, billed from when the GPU attaches: the installs, the Pi3X weights download (about 5.4 GB) and one forward pass. Queue time is not billed.

## Tear down

With the same variables set:

```bash
databricks bundle destroy
```

This removes the App, the job, the volume (with its files) and the schema. The tables are not bundle resources but live in the schema; if the schema delete is refused because it still holds tables, drop it yourself and run `destroy` again:

```sql
DROP SCHEMA <your_catalog>.drone_swarm_4d CASCADE;
```

## Licences

- Code (the bundle, the notebook, the App and the job): the repository's [LICENSE](../../LICENSE.txt).
- Data ([`nick-karpov/drone-swarm-4d`](https://huggingface.co/datasets/nick-karpov/drone-swarm-4d)): [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).
- Third-party software used here, each under its own licence: [three.js](https://github.com/mrdoob/three.js) (MIT, loaded from a CDN by the viewer), [FastAPI](https://github.com/fastapi/fastapi), [Pi3 / Pi3X](https://github.com/yyfz/Pi3) (code BSD-3-Clause; the `yyfz233/Pi3X` weights are CC BY-NC 4.0), [huggingface_hub](https://github.com/huggingface/huggingface_hub), [OpenCV](https://opencv.org/license/), [SciPy](https://scipy.org/) and [Apache Arrow](https://arrow.apache.org/).

## How to get help

For questions or bugs, please open a GitHub issue and the team will help.
