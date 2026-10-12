# Spatial Reconstruction from Any Video

Turn an ordinary video (from a drone, phone, robot or vehicle camera) into a 3D scene on Databricks serverless GPU: camera poses, a point cloud and, optionally, a Gaussian splat. Results are published progressively to a Unity Catalog volume while the job runs, so a viewer can show the scene as it builds up.

The example has two parts:

- **[`SKILL.md`](SKILL.md)**: the recipe. A step-by-step pipeline (ingest, frame selection, masks, depth preview, matching, SfM, QA, densify, splat, progressive publishing), plus optional region updates ("paint-in") and localization of a new clip against an existing model. It also covers Databricks specifics (serverless GPU jobs, dependencies, volumes, billing, GPU choice) and a list of approaches that did not work. Written so that a person or an AI coding agent can follow it.
- **[`job_skeleton/`](job_skeleton/)**: a minimal, generic job that implements the core path: video → frames → COLMAP SIFT matching → mapper → bundle adjustment → QA → point cloud, with optional gsplat training.

## Who it's for

Developers and data teams who want 3D reconstructions from video they already have (inspections, site surveys, robotics, digital twins) and want to run them as governed, pay-per-use jobs on Databricks instead of on a dedicated GPU workstation.

## Prerequisites

- A Databricks workspace with **serverless GPU compute (AI Runtime)** enabled
- A **Unity Catalog volume** for inputs and outputs, with `READ VOLUME` and `WRITE VOLUME` on it (plus `USE CATALOG` / `USE SCHEMA`)
- Permission to run serverless GPU jobs, and a CLI that can submit AI Runtime jobs (the `air` CLI or `databricks air`, authenticated with a profile)
- Outbound internet from the job, to install COLMAP (conda-forge) and Python packages at start-up

## Folder contents

| Path | What it is |
|---|---|
| `SKILL.md` | The full recipe, defaults, indicative numbers and failure modes |
| `job_skeleton/job.yaml` | Serverless GPU job spec (A10 by default, timeout set, no retries) |
| `job_skeleton/entry.sh` | In-job setup: installs a pinned, checksummed CUDA build of COLMAP via micromamba, then runs the job |
| `job_skeleton/recon_job.py` | The reconstruction job and the progressive publisher |

## Quickstart

1. **Upload a video** to your volume:

   ```bash
   databricks fs cp my_clip.mp4 dbfs:/Volumes/<catalog>/<schema>/<volume>/inputs/my_clip.mp4 --profile <profile>
   ```

2. **Fill in the placeholders** in `job_skeleton/job.yaml`: `<workspace-folder>` for the MLflow experiment, `<run_id>`, and the `--video` and `--run` paths in `command`. Pick a new run id for each run. Adjust `accelerator_type` and `timeout_minutes` if needed.

3. **Submit the job** from the `job_skeleton/` folder (the code snapshot uses `root_path: .`):

   ```bash
   cd demos/spatial-recon-any-video/job_skeleton
   air run --file job.yaml -p <profile>      # or: databricks air run --file job.yaml -p <profile>
   ```

4. **Find the outputs** in `/Volumes/<catalog>/<schema>/<volume>/runs/<run_id>/`:
   - `manifest.json`: list of published assets, stage timings, QA result and final `status` (`running`, `complete` or `failed`)
   - `assets/NNN_<kind>.<ext>`: `frames_chosen` (JSON), `points_final` (PLY point cloud), `splat_final_ply` (if enabled) and the COLMAP `log`
   - `events/NNNNNN.jsonl`: event log, written in immutable chunks
   - `progress.json`: heartbeat

   Open the PLY files in any point-cloud or splat viewer, or poll `manifest.json` to show assets as they arrive.

Useful options for `recon_job.py`: `--priors priors.csv` (see below), `--masks <dir>` (COLMAP masks, e.g. sky and water), `--max-frames`, `--mapper global|incremental`, and `--splat-steps N` to train a Gaussian splat. Splat training needs gsplat installed and `GSPLAT_EXAMPLES` pointing to a checkout of gsplat's `examples/` folder; `entry.sh` does not install these, so add them there if you enable it.

The skeleton can also run locally on CPU for a quick check, with COLMAP 4 on `PATH` (or set `COLMAP`) and `opencv-python` installed:

```bash
python job_skeleton/recon_job.py --video my_clip.mp4 --run ./runs/test --max-frames 60 --max-side 960 --gpu 0
```

## Using SKILL.md with an AI coding agent

`SKILL.md` has skill front matter (`name`, `description`), so it can be used directly as an agent skill:

- **Claude Code**: copy this folder to `.claude/skills/video-to-3d-on-databricks/` in your project (or `~/.claude/skills/`). The agent loads it when you ask it to plan, build or debug a video-to-3D pipeline.
- **Genie Code and other agents**: add `SKILL.md` as a skill or instructions file where the tool supports it, or paste it into the conversation as context.

Then ask, for example: "Adapt the job skeleton to my clip and priors, run it on a 1×A10 and check the QA result."

## Inputs and outputs

**Inputs**
- A video in any format ffmpeg/OpenCV can decode
- Optional pose priors as `priors.csv` with header `t_s,x,y,z`: timestamps in seconds from the start of the video, positions in metres in any local metric frame (e.g. ENU from GPS, odometry or a SLAM track). With priors, match pairs are predicted from positions and the model is aligned to the priors' frame and scale. Without them, everything still works, in an arbitrary frame and scale.
- Optional COLMAP masks

**Outputs**
- Camera poses and a sparse point cloud (COLMAP model, exported as PLY)
- Optionally a Gaussian splat (PLY)
- A manifest with QA (registered-frame fraction, reprojection error, pass/fail) and stage timings

## Runtimes and costs (indicative only)

From test runs, typically one run per configuration. Your numbers will differ with clip length, resolution, scene and region.

| | 1×A10 | 8×H100 |
|---|---|---|
| Full reconstruction + splat, 1-minute clip | about 10 min | about 6 min |
| Cost at AWS list price | about $0.40–0.60 | about $5.50 |

Add serverless start-up latency (typically 1 to about 15 minutes, not billed while queued). The skeleton alone (no splat) is much shorter. See `SKILL.md` §3 for billing details and GPU choice; check the current Databricks pricing page for your cloud and region.

## Limitations

- **The job skeleton has only been tested locally, on CPU with COLMAP 4.0.4**, on a short clip, with and without priors. It has **not yet been run as a Databricks job**: the GPU paths, the in-job CUDA COLMAP install, gsplat training and volume I/O are untested. Run it once on a short clip before relying on it.
- The pipeline and numbers in `SKILL.md` were developed **mostly on aerial video**. Ground, handheld and indoor footage should work with the same steps but has seen far less testing.
- The skeleton implements the core path only. Masks, depth previews, QA remediation, densification, paint-in and localization are described in `SKILL.md` but not included as code.
- Reconstruction quality depends on the footage: motion blur, little parallax (e.g. hovering or pure rotation), water, reflections and sky all cause failures. `SKILL.md` lists the known failure modes.

## Third-party tools and licences

This example installs or refers to third-party software and models. Each has its own licence; check them before use, especially for commercial use (several feed-forward 3D model checkpoints are non-commercial).

- [COLMAP](https://github.com/colmap/colmap) ([licence](https://colmap.github.io/license.html))
- [gsplat](https://github.com/nerfstudio-project/gsplat) ([licence](https://github.com/nerfstudio-project/gsplat/blob/main/LICENSE))
- [micromamba / mamba](https://github.com/mamba-org/mamba) ([licence](https://github.com/mamba-org/mamba/blob/main/LICENSE)) and [conda-forge](https://conda-forge.org/)
- [OpenCV](https://github.com/opencv/opencv) ([licence](https://opencv.org/license/))
- Models and tools referenced in `SKILL.md` only (not installed by the skeleton), e.g. Brush, SegFormer, Depth Anything, VGGT, MASt3R, LightGlue, PlayCanvas: see each project's repository for its licence.

## How to get help

Databricks support doesn't cover this content. For questions or bugs, please open a GitHub issue and the team will help on a best effort basis.
