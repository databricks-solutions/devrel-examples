---
name: multiview-4d-on-databricks
description: Reconstruct a moving person (or any dynamic subject) in 4D, as a time-varying coloured point cloud, from 2 or more synchronised moving cameras such as drones, phones or robots, on Databricks serverless GPU (AI Runtime). Covers clock sync, person masks, camera tracks with Depth Anything 3, per-instant Pi3X with known poses, seam-free merging, temporal smoothing, QA, and running it reliably on AIR (sharding, progress and ETA through MLflow, smoke tests, hard exits, caching). Use when planning, building, running or debugging a multi-camera 4D pipeline, or choosing AIR shapes for one.
---

# 4D reconstruction from a few moving cameras, on Databricks AI Runtime

This recipe comes from a working capture: 2–3 small consumer drones filming one person outdoors from 2–5 m away, rebuilt at 29.97 slices per second with 40–110 k points per slice. The released result is the public dataset [`nick-karpov/drone-swarm-4d`](https://huggingface.co/datasets/nick-karpov/drone-swarm-4d), and the [drone-swarm-4d demo](../drone-swarm-4d/) is its viewer. The numbers are from those runs. Use them as starting points, not as guarantees.

The core idea is to split the problem in two. One model tracks **where every camera was through the whole clip**. Another builds **the subject's shape at each instant** from all the cameras' frames for that instant, conditioned on those poses. Everything else is sync, masks, alignment and clean-up.

```
N videos + per-frame clock ─► 1 sync ─► 2 masks ─► 3 camera tracks (DA3, whole clip, metric from telemetry)
                                                          │
             per slice: 4 Pi3X(all views, K, poses) ─► Sim(3) to the tracks ─► 5 merge + temporal smoothing ─► 6 colour
                                                          │
                                         7 cloud/sNNN.bin + index.json ─► 8 QA
```

## 1. Sync: one clock for every frame

- **Use the cameras' own clocks, not arrival time.** Many cameras embed a per-frame device timestamp in the video stream (for example in H.264/H.265 SEI user data) or in a sidecar. Find one that shares a clock with the device's telemetry, unwrap it if it is truncated, and anchor it on the telemetry.
- **Map each camera clock to the host.** Fit a lower envelope of host arrival time against camera time (3 s bins, lowest 5%, linear), which removes link jitter. Then assign frames to a fixed slice grid (29.97 Hz here).
- **Typical results:**
  - drift against the host of 2.6–18 ppm, and envelope residuals of 5–11 ms;
  - a phone LED strobe filmed by all drones agreed to ±2–3 ms;
  - onboard 4K frames matched to live frames by camera time within 1 ms (0.5 ms median, the timestamp's quantisation).
- **How much sync you need:** in simulation, 30 ms of error is harmless and 100 ms costs 2.8 dB of rendered quality. With other cameras, any per-frame hardware or SDK timestamp works. Verify it once with a flash or strobe.

## 2. Masks: two models must agree

- **Keep the intersection:** YOLO11x-seg instance mask ∩ SAM 2 (`sam2_b`, prompted with the YOLO box), minus vegetation by HSV hue (green 70–165, magenta 280–340).
- **Clean-up:** erode by 1 px (3×3 ellipse) and drop islands smaller than 2% of the largest component. Make the masks at full video resolution.
- **Picking the subject:** take the instance with the best IoU against the tracked box (median IoU 0.95). Log the share of each frame's YOLO mask that survives the intersection, and review frames under 0.85.
- **Don't cross-check silhouettes between cameras with dilated masks.** That check deleted 36–48% of the leg pixels and produced cut-off legs. Trust each camera's own mask.

## 3. Camera tracks through the whole clip (Depth Anything 3)

- **Model:** DA3-NESTED-GIANT-LARGE-1.1, multi-view poses at `process_res` 504.
- **Global, then local:**
  1. Solve A runs on keyframes (every 10th slot, all cameras, about 50 pictures) and defines the world frame.
  2. Local chunks (8 keyframe anchors + 18 in-between pictures each) are tied to A by a rotation-first similarity.
  3. A second, independent solve B on the half-way slots is a cross-check (it agreed to 1.9 cm and 0.53° median).
- **Clean the tracks:** reject rotation outliers (more than 2.5° from their neighbours, or more than 3° from the gimbal attitude), then smooth with a Gaussian (σ = 3 slots).
- **Get metric scale from telemetry, not the model.** DA3 came out about 26% short. A joint fit to the drones' own odometry gave ×1.348, and the per-drone scales had to agree within 6%. The trajectory then matched odometry to 3–5 cm rms. Take the up direction from gimbal-levelled cameras.
- **Gate the tracks before any depth work.** The smoke test caught the 26% scale error, not the full run.
- **Depth resolution has a sweet spot:**

  | `process_res` | s/picture (A100) | peak GiB | person drift vs 1008 |
  |---|---|---|---|
  | 1008 | 0.26 | 13.5 | reference |
  | **1512** | 0.87 | 19.6 | 12.7 cm |
  | 2016 | 1.58 | 28.0 | **87 cm** |
  | 2520 | 2.15 | 43.0 | 279 cm |

  Above 1512, DA3 drifts: depth jumps and heads flatten into blobs. More pixels are not more accuracy.

## 4. The shape at each instant (Pi3X, conditioned on the poses)

- **Model:** `yyfz233/Pi3X`, pinned by revision. It takes all cameras' frames for the slice at once, with intrinsics and poses (`mask_add_ray`, `mask_add_pose`), in bf16.
- **Input at about 672×378** (about 255 k pixels, sides multiples of 14). Downscale with `INTER_AREA` and scale the intrinsics to match. **Higher input resolution made the shape worse,** because the model was trained at this size.
- **Alignment:** a per-slice Sim(3) from the model's cameras to the tracks. Solve rotation first (the chordal mean of R_track·R_modelᵀ), then scale and translation from the camera centres.
  - Pi3X's own scale is 20–37% small, and that is fine.
  - Even when conditioned, it moves the cameras by 0.4–0.6° and 1.5–3.5 cm, so log those as QA.
- **Cost:** 0.15–0.19 s per slice and about 8 GiB. A 300-slice clip is about one GPU-minute, so a 24 GB A10 is enough.

## 5. Merge and steady

- **Cut only true depth discontinuities.** A blunt log-depth edge threshold (0.02) also cut shirt folds and left cracks. Fixing it took the holes inside the mask from 12–15% down to 3–4%.
- **Seam-free merge:**
  - trim points within 4 px of the mask edge, flying pixels more than 5 cm behind their local minimum, and grazing points (normal more than 72° from the view);
  - weight each view by cos θ × edge ramp × angle ramp × f/z;
  - keep regions that only one camera sees. Most of the subject is in such regions with 3 widely spread cameras.
- **Smooth the camera paths, not the points.** Fit a robust Huber spline (knots every 0.4 s, quaternion spline for rotation), then re-project the depth through the smoothed cameras.
  - Smooth all cameras jointly: smoothing them one by one broke consistency (2.8 → 4.0 cm).
  - **Keep the per-slice scale.** Smoothing it made flicker worse (1.41 → 2.08 cm), because it compensates the model's per-instant depth.
  - This one step removed the visible jitter (1–5 cm rms).

## 6. Colour from real pixels

- Take colour from the sharpest source (onboard 4K over the live stream: crops come out 2–3.5× sharper).
- Remove each camera's haze veil (black level).
- Fit a per-camera 3×3 + offset colour transform per second, with Huber IRLS on points that two cameras see within 1.5 cm and a ridge prior towards the identity. Blend with feathering. This took ΔE from 23 to 11–12.

## 7. Output format

- `cloud/sNNN.bin`: little-endian, 9 bytes per point (int16 x, y, z in mm, then uint8 r, g, b).
- `cloud/index.json`: `{format, fps, slices: [{i, t_s, file, n}], bounds}`.
- The clip frame is in metres, z up, with the origin on the floor under the subject at slice 0.
- The [drone-swarm-4d App](../drone-swarm-4d/) plays this format directly.

## 8. QA: score it against what a camera really saw

- **Hold out one camera:** rebuild from the others, render into the held-out view, and measure PSNR and LPIPS inside the mask.
- **Cross-camera disagreement:** held-out LoFTR matches between camera pairs, lifted to 3D. In these clips it was 3.0 cm median and 6.8 cm p90.
- **Body checks:** head and shoulder gap, legs present, height plausible (1.85 m here), and flicker (also motion-compensated).
- **Per slice:** the Sim(3) camera rotation and centre error, and Chamfer distance against a reference when you have one (`recon4d_job.py` writes all of these).

## 9. How many cameras

From a simulation sweep (3,936 cells, 2 seeds each, run as packed tasks on 8×H100 AIR jobs):

| hovering cameras | 1 | 2 | 3 | 4 | 6 |
|---|---|---|---|---|---|
| rendered PSNR (dB) | 15.0 | 17.1 | 21.4 | 21.0 | **24.1** |

- **Six cameras** at staggered heights and even angles gave about **2.8 cm** Chamfer, 9 dB better than one camera.
- **Simultaneous capture beat sequential capture by 8.2 dB.**
- With three cameras about 120° apart, most of the body is seen by only one camera, so its depth is a learned guess and the seams between cameras disagree by centimetres to decimetres. **Pairs with real overlap are what turn guessed depth into measured depth.**

---

## 10. Running it on Databricks AI Runtime

The heavy stages are short, independent GPU tasks, which suits AIR well. Across 445 jobs (about 524 GPU-hours, peaking at about 70 H100s at once):
- the median platform overhead from submit to teardown was **44 s** (p90 76 s), with about 10 s to the first log line;
- 16 of 214 measured starts queued for 79–535 s.

**Shapes:**
- **1×A10** for per-slice Pi3X: about 1 GPU-minute per clip.
- **1×H100** for DA3-Giant at 1512 (about 20 GiB peak, 480 pictures in about 5 min) and for 4D splat training (four variants side by side, one H100 each, about an hour, about $51 in total).
- **8×H100** to pack many small independent tasks: sweeps, simulations, per-seed runs.

**Layout: one job per independent unit.**
- Shard the slices across independent jobs (`--shard i/N`). Each shard infers a halo of `smooth/2` slices on each side, so the shards' output is byte-identical to a single run (tested).
- Run sweeps as one job per variant or seed, not as a loop inside one job. A failure then costs one cell, not the sweep.
- Cap concurrency and set a deadline on the outer loop.

**Progress and ETA.**
- Log `max_steps` (a param) and `epoch` (done / total) through `MlflowClient` with an explicit run id, and AIR's ETA predicts the end to within seconds.
- Two traps froze the ETA at 5%:
  1. `mlflow.start_run` in prep consumes `MLFLOW_RUN_ID` from the environment. **Capture it at import time.**
  2. The active run is per thread. Pass the run id to every thread that reports.
- Report progress from prep too, not only from the main loop.

**Reliability.**
- **Exit hard.** Wrap `main` so that any exception prints a traceback and calls `os._exit(1)`. Add an in-job watchdog timer and a stall watchdog (no progress for 15 min → `faulthandler` dump, then exit). A dead child process once kept a GPU for 11 minutes.
- In shell entrypoints, use `set -euo pipefail` and `exec` the Python process, so failures reach the job's status.
- Set `timeout_minutes` and `max_retries: 0`. Re-submit by hand after reading the log.
- **Smoke-test through the real entrypoint and output path** (`entry.sh → job`, a few slices, about 3 min), never a toy copy. A small smoke test can still miss scale-dependent stalls (`svd(full_matrices=True)` on a big matrix cost 10 min), so smoke-test at realistic sizes where it matters.
- **Cache data prep on the volume,** keyed by its inputs and settings. One smoke test went from 31 minutes (cancelled) to 7. Cache model weights the same way.
- **Volumes take whole-file writes:** write `name.tmp`, then rename, and fall back to copy. Copy videos to local disk before decoding, because FUSE seeks are slow. Write a manifest last, so consumers know a shard is complete.

**Dependencies.**
- The base environment ships torch, numpy and OpenCV. Pin nothing that is already installed, because pins force slow downgrades.
- Pip-install only what is missing (pinned) after a `JOB_START` timestamp, so platform start-up and your own setup are separable.

**Neoclouds alongside AIR.** For quick single-GPU experiments, rented consumer and workstation cards (on Vast here) ran most per-clip 4D variants for under a dollar each. Big sweeps went to AIR. Keep the job script portable between them: the same entrypoint, inputs on a path, outputs written whole.

## 11. Job skeleton

`job_skeleton/` runs steps 4, 5 (per-slice alignment smoothing and cross-view fusion) and 7 on a clip in the release layout:
- `recon4d_job.py`: the clip driver. It handles shards with a halo, a single decode pass per video, per-slice Pi3X, Sim(3), smoothing, person cut and fusion, writing clouds and per-shard index, report and manifest files, MLflow progress and a hard exit.
- `pi3x_instant.py`: one instant, which is also a standalone tool. Its `--model stub` option exercises everything without a GPU.
- `entry.sh`, `job.yaml`: the AIR job.

**Check the plumbing locally in seconds** with the synthetic fixture from the drone-swarm-4d demo:

```bash
python ../drone-swarm-4d/tests/make_fixture.py /tmp/fx
cd job_skeleton
python recon4d_job.py --release /tmp/fx --clip clip1_three_drones --out /tmp/r4d --model stub --device cpu
```

**Then on AIR:**
1. Upload a clip in the release layout to a volume.
2. Fill in the `<...>` placeholders in `job.yaml`.
3. Smoke-test with `--max-slices 10`.
4. Submit one job per shard: `air run --file job.yaml -p <profile>`.

To reproduce the release's camera tracks (step 3), the seam-free merge, the spline smoothing and the colour fit, follow the settings above. The skeleton keeps the per-slice path simple and testable.

## Checklist for an agent

1. Confirm a shared clock across cameras, to within about 30 ms, and verify it with a flash.
2. Masks: two models intersected. Log agreement and review low frames.
3. Camera tracks over the whole clip, with metric scale and up from telemetry. **Gate them before depth work.**
4. Per slice: Pi3X at about 672 long side with poses. Sim(3) per slice; keep the per-slice scale.
5. Smooth the camera paths jointly, merge seam-free, then colour.
6. QA by holding out a camera. Record the numbers next to the output.
7. AIR: a smoke test through the real entrypoint, sharded independent jobs, MLflow `epoch`/`max_steps` with an explicit run id, `timeout_minutes`, `max_retries: 0`, hard exits, cached prep.
