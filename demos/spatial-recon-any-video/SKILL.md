---
name: video-to-3d-on-databricks
description: Reconstruct a 3D scene (camera poses, point cloud, Gaussian splat) from aerial or ground video (e.g. drones, phones, robots, vehicle cameras) on Databricks serverless GPU, publish results progressively while the job runs, and optionally update one region of an existing model ("paint-in") or localize a new clip against it. Pose, IMU or GPS priors are optional. Use when planning, building or debugging such a pipeline, or choosing Databricks compute and storage for it.
---

# Reconstructing and updating 3D scenes from any video feed on Databricks

This is a recipe that a person or an AI agent can follow. The steps are general and camera-agnostic. The numbers are **indicative results from outdoor and indoor test scenes, typically one run per configuration**. Treat them as starting points and orders of magnitude, not guarantees.

Two conventions:
- **Priors are optional.** "Priors" means any per-frame pose information: GPS, IMU or attitude, robot odometry, phone AR poses (ARKit/ARCore), or a SLAM track. With priors you get metric scale, a known frame, faster matching and better QA. Without them everything still works, in an arbitrary frame and scale.
- **All thresholds are relative.** Lengths are multiples of **h**, a scene-scale unit: camera height above ground when you have it, otherwise the median camera-to-scene depth. Pixel thresholds are stated at a reference width. Never tune thresholds to one clip; if something works only after tuning, record it as a finding, not a default.

---

## 1. Architecture: one GPU job, one process, local disk, and a run folder on a volume

```
video (+ optional priors) on a Unity Catalog volume
        │
        ▼
ONE serverless GPU job (timeout set), ONE Python process:
  copy inputs to local disk ─► select ─► masks ─► depth preview ─► match ─► SfM/BA ─► QA ─► densify ─► splat
        │ every stage hands snapshots to one publisher thread (stages never wait on publishing)
        ▼
run folder on the volume:  manifest.json            (rewritten whole, last)
                           assets/NNN_<kind>.<ext>  (immutable)
                           events/NNNNNN.jsonl      (immutable chunks, every ~3 s)
                           progress.json            (heartbeat)
        │
        ▼
viewer polls manifest.json (Files API or a mirror) and fades assets in
```

Why this shape:
- **With separate jobs per stage, overhead dominates.** A split flow (features on one GPU job, reconstruction on CPU clusters, splatting on another GPU job) spends more time on cluster start-ups, installs and multi-GB transfers than on compute.
- **One process removes the hand-offs.** Intermediates stay on local disk, and the volume holds only inputs, published assets and resumable checkpoints.
- **Long-term production option:** a pinned container image (or a classic GPU job cluster with one) removes per-run installs and start-up variance. In-job installs are fine for prototyping (§3).

---

## 2. The pipeline, step by step

Every step lists its defaults, typical numbers and failure modes. Typical numbers refer to a clip of about 1 minute (about 100 geometry frames at 1080p) on a single A10 unless stated otherwise.

### Step 1. Ingest (video plus optional priors)

- **Input:** any container ffmpeg can decode (HEVC is fine), plus optional timestamped priors.
- **Copy inputs to local disk first** (`/local_disk0` when writable, else `/tmp`). Never run COLMAP databases, SQLite or training I/O on a volume path.
- **Clock alignment:** fit the lag between video and priors over a grid (for example −0.4 to +0.2 s in 0.02 s steps). Lags of a few hundred milliseconds are common.
- **Convention check:** fit a Sim3 between an early reconstruction and the priors, trying axis orders and sign flips. Don't trust the docs for the axes. Common traps:
  - a heading or yaw field offset by 90°;
  - an altitude axis that is left-handed relative to the image geometry. A wrong sign can triple the trajectory residual and gives negative scales on vertical motion.
- **No priors:** the model has arbitrary scale. Scale it with metric monocular depth, a known object, or printed fiducial markers. Markers of known size gave room dimensions within about 1–2% of a tape measure.

### Step 2. Frame selection

- **First pass:** the sharpest frame per time window (variance of the Laplacian).
- **Second pass, coverage-based:** keep frames until every cell (0.18 h) is seen by 3 views at baseline angles of 5–30°, with consecutive overlap ≥ 0.6 and depth ≤ 3.5 h. Typically about 280 candidates become about 100 geometry frames per minute of video.
- **Select over the whole clip for offline jobs.** Selecting in short chunks (about 8 s) kept roughly 25% fewer frames and cost about 2 dB of splat quality. Use chunked selection only for live streams.
- **Drop degenerate motion:**
  - take-off and landing;
  - climbs or hovers with the camera pointing straight down at flat ground;
  - a phone pointed at the floor;
  - a robot spinning in place.

  Such frames don't constrain camera height or baseline. They have placed cameras about 1 m (up to about 3 m) off and created a duplicated "ghost" copy of the area in the splat. Drop them or pin them.

### Step 3. Masks (sky, water, reflective and refractive regions)

- **Default:** SegFormer-B5 (ADE20K classes) at 640 px input, masks dilated by 0.005 × image width.
  - Mask **water, other refractive or reflective surfaces, and sky** for feature extraction.
  - Mask **sky only** for splat training.
- **Why:** refraction through water triangulates a submerged surface about 1 m above its true height, creating a ghost layer.
- **Failure modes:**
  - A semantic class can cover an entire object (for example, all of a water body), which leaves no SfM points there. Anything downstream that needs geometry in that region must use dense monocular depth instead.
  - Importing the segmentation framework can take about 30 s. Preload models in a background thread from t = 0.
- **Splat masks:** Brush and gsplat both accept masks. In Brush, RGBA alpha is a transparency target, not "ignore". Leaving water unmasked in the splat is the default, because masking leaves an untrained hole.

### Step 4. Monocular depth preview (minutes before SfM finishes)

- **Default:** Depth Anything V2 Small at 294 × 518, every 6th pixel, scaled to prior-anchored points or a ground prior. Publish it as `points_depth`, typically 30–90 s into the job.
- **Multi-view feed-forward models** (Depth Anything 3, VGGT, Pi3) turn 64 frames into a dense, prior-aligned cloud in about 2–4 s on an H100 or 8–11 s on an A10. That is 30–60× sooner than the first SfM cloud.
- **Accuracy is coarse.** At best about 90% of points fall within 0.5 m on a scene tens of metres across, and cameras are about 10× worse than SfM. In tests, Depth Anything 3 > Pi3 ≈ VGGT ≫ MASt3R (global alignment) for this use.
- **Keep the model resident.** A cold load adds 10–15 s plus a few seconds of first-call warm-up.
- **Check the licences.** Many feed-forward checkpoints are non-commercial. Permissively licensed variants exist for some model families.

### Step 5. Matching

- **Features:** CUDA SIFT, 6,000 per image at 1,920 px.
- **Pick features by pose precision, not match count.** SIFT (about 0.6 px median reprojection) beat ALIKED+LightGlue (about 1.0 px) by about 3 dB of splat PSNR on the same frames, even though the learned matcher produced more matches.
- **Pairs with priors:**
  - sequential (window 4) + overlap (≥ 0.25) + revisit (gap ≥ 8 s, overlap ≥ 0.2), at most 30 per image;
  - then an epipolar prefilter from the priors (3°), GPU mutual-nearest-neighbour matching, and MAGSAC essential-matrix verification on CPU workers.
  - Typically about 75% of predicted pairs verify.
- **Pairs without priors:** sequential plus image retrieval (a global descriptor, top-k), plus loop detection for long clips.
- **Don't match every pair.** Exhaustive matching of 200 frames meant about 20,000 pairs, half the job's wall time, and a 10-minute gap with nothing published, with the GPU idle. The cost was CPU verification of pairs that don't overlap. Predicted pairs cut matching from about 10 minutes to about 35 s.
- **Failure mode:** matching against photos taken from a very different viewpoint fails; see §4.

### Step 6. SfM and bundle adjustment

- **Default:** COLMAP 4 global mapper (images only) → Sim3 to priors → merge tracks + BA. If that fails, fall back to prior-initialised triangulation + BA.
- **Speed settings:** `skip_retriangulation`, `ba_num_iterations = 1`. The mapper then takes about 30–50 s for about 100 frames.
- **Typical results:**
  - all geometry frames registered, at about 0.5–0.6 px median reprojection;
  - Sim3 residual to priors around 0.1–0.2 m with consumer-grade GPS/IMU;
  - a 5-minute, 700-frame clip with prior initialisation: about 10 min of CPU.
- **CPU matters.** BA and verification run on CPU, so a fast GPU on a weak host is slow (§3).

### Step 7. QA (automatic checks and remediation)

- **Severity:** sum over flags of max(0, value / threshold − 1). Rank candidate models by (severity, double-layer share, median residual).
- **Flags (relative to h):**
  - double-layer cell share > 0.10 (ghost layers);
  - temporal layering;
  - height disagreement on revisits > 0.10 h;
  - prior fit: median > 0.07 h, plus an outlier count. Don't use RMS;
  - scale error > 10%.
- **Drop gross outlier cameras first:** residual > max(8 × median, 0.5 h), at most 5% of cameras. A single bad camera can triple the prior-fit RMS.
- **Remediation ladder, run as parallel alternatives:** merge tracks + BA for layer and height flags; drop frames for camera-fit flags; switch the reconstruction path only at severity ≥ 1. Accept "pass (marginal)" if severity < 0.25 or every flag is ≤ 1.5× its threshold.
- **Pre-register gates and don't relax them after the fact.** Watch out for gates that measure the priors' drift (for example barometric altitude) instead of reconstruction error. If a gate is wrong, replace it with a documented one before the next run.

### Step 8. Densify

- Register extra frames into the fixed model for the splat only: 6 nearest neighbours, ≥ 40 inliers.
- This typically gives 2–2.5× as many training views as geometry frames.

### Step 9. Gaussian splat training (gsplat)

- **Default:** gsplat with ADC (adaptive density control) and coarse-to-fine resolution (1/4 → 1/2 at 15% → 1/1 at 40%):
  - 10k steps, at most 750k splats, SH degree 3, masks on;
  - initialised from tracks seen in ≥ 2 views;
  - preview exports about every 12 s (capped at 250k splats).
- **Speed:** gsplat trains at about 40 steps/s on an A10, against about 25 for Brush, with slightly better quality. On full-size runs an H100 trains about 1.9× faster than an A10. Small runs are CPU or launch bound and see no gain.
- **Typical quality:** held-out non-sky PSNR about 25–26 dB, SSIM about 0.82, on a 1-minute clip.
- **Turn pose and appearance optimisation off.** It trains faster, but held-out PSNR drops by several dB because per-image corrections don't transfer to new views.
- **Early splat:** a second, cheaper trainer (≤ 10k steps, 300k splats, SH1) runs concurrently so a preview exists sooner.
- **Alternatives:** Brush (Rust/wgpu, Vulkan) also runs on Databricks serverless GPU.

### Step 10. Progressive publishing (manifest + event log)

- **Run-folder contract,** shared by producer, mirror and viewer:
  - `manifest.json`: `assets[]` (seq, kind, file, bytes, wall time, frame, counts, metrics, qa), `stages{}`, `events{chunks, count, last_type}`, `status`.
  - Asset kinds: `prior_path`, `photos_placed`, `cameras_chosen`, `match_graph`, `points_depth`, `points_prior`, `points_rough`/`points_refined`/`points_final`, `cameras_final`, `splat_preview`, `splat_final`, `splat_final_ply`.
  - Event types: `stage`, `frame_selected`, `pair_verified`, `points_added`, `points_remapped`, `burst`, `camera_dropped`, `qa_flag`, `qa_resolved`, `splat_progress`.
  - Consumers must ignore unknown kinds, events and fields.
- **Rules:**
  - Write each asset completely, then rewrite `manifest.json` whole.
  - Publish the first asset of each kind immediately, then about every 15 s.
  - Write events as new chunk files about every 3 s; never rewrite one.
- **Typical timeline (1-minute clip, job time):**

  | | 1×A10 | 8×H100 |
  |---|---|---|
  | photos placed in 3D | 20–60 s | about 20 s |
  | first SfM point cloud | about 2 min | under 2 min |
  | final splat | about 10 min | about 6 min |

  - Add the platform's start-up latency (§3) on top of these.
  - Publishing overhead is a few seconds per job.
- **Viewer:** a WebGL2/WebGPU Gaussian-splat engine with compressed formats. In a renderer comparison, PlayCanvas with SOG compression worked best.
  - SOG is about 15× smaller than an SH3 PLY (about 25 MB vs about 350 MB for 1.5M splats).
  - Load time is sub-second against several seconds for PLY.

### Step 11 (optional). Paint-in: update one region of an existing model

Use this when a new clip covers part of a scene you already have, so only the update region should change. Steps:
1. **Localize** the new clip into the existing model (step 12), then run a **joint BA** of the new frames against fixed anchors from the existing model.
2. **Update region:** a semantic box (dominant class at the centre of interest, its 3D cluster, an oriented box with 12% padding). Refit its vertical extent to the occupied height + 10%.
3. **Freeze everything outside the box.** Inside it, a thin band of existing splats is trainable, the core is replaced, and new splats come from the clip's SfM points.
4. **Depth-gated supervision.** For each training pixel, decide from frozen-model depth plus dense depth of the new clip:
   - the first surface is inside the box → supervise with the new frame;
   - the ray passes through the box → use the frozen render as the target and penalise box opacity;
   - the pixel is occluded → exclude it.
5. **Water and planar refractive surfaces:** RANSAC a plane on boundary (rim) points, then add coplanar splats with SH whose height is refined during training.

Typical result (A10, 7,000 steps, base model of about 1.5M splats, about 150k trainable plus about 40k plane splats):
- inside-region held-out PSNR from about 11 dB (stale model) to about 20–21 dB;
- **haze** (box opacity on rays that should pass through it) **about 10× lower** than without depth gating;
- job about 15 min; **well under $1 at list price**.

Failure modes:
- **Without depth gating, inside-region PSNR can look higher,** because box splats paint over the background with stale content. That is the haze itself, so measure haze explicitly.
- **Semantic masks can remove every SfM point on the target.** The gate then calls it "pass-through". Gate with dense monocular depth instead.
- **Plane fitting:** area-weighted sweeps can bias the fitted plane height. Check plane height against rim points.

### Step 12 (optional). Localize a new clip against an existing model

1. **Coarse:** gravity-aligned yaw search × FFT voxel cross-correlation, then trimmed ICP of the new clip's own reconstruction against the map's points. No appearance is needed, it takes seconds, and you should check that the correlation peak is unique.
2. **Fine, render-and-match:** render the existing splat at each predicted pose, match the real frame against the render, lift matches with the rendered depth, solve PnP, and iterate.
   - MASt3R against renders: in tests, **every frame correct, about 95% within 3 px, no false accepts**, about 0.5 s per frame on an A10.
   - DISK+LightGlue against renders: about 80% correct.
3. **Joint BA gate:** ≥ 90% of frames registered, median reprojection ≤ 1.5 px at 960 px, split-half consistency ≤ 0.10 h, and a held-out render check.
4. **A few anchors aren't enough for paint-grade.** A Sim3 from priors fitted on many frames still leaves about 0.2 m / 2° / 25 px. Paint-grade needs per-frame localization.

---

## 3. Databricks specifics

### Serverless GPU (AI Runtime) jobs
- **Spec:** a YAML with `compute.accelerator_type` (`GPU_1xA10`, `GPU_1xH100`, `GPU_8xH100`), `environment.version`, a code snapshot, `command`, `max_retries: 0` and **`timeout_minutes`**. See `job_skeleton/job.yaml`.
- **Always set a timeout and add an in-job watchdog.** End with `os._exit`, because a stray non-daemon thread or blocked queue can keep a finished job holding a GPU.
- **Start latency varies, typically 1 to about 15 minutes.** Make the job's first output line a timestamped start marker, so platform start-up and your own setup are separable.
- **Use submitted jobs, not open-ended interactive GPU sessions.** Interactive sessions can shut down on an idle client and kill a run. They also bill idle time: an 8×H100 session can cost about $25 for a 6-minute job.

### Dependencies: don't pin what's preinstalled; install what's missing, inside the job
- The GPU base environment already ships recent torch/CUDA, numpy, scipy, OpenCV and transformers.
- Pinning older versions forces downgrades **before your script starts**. That can mean 25+ minutes of silence, or hangs.
- **Fix:** pin nothing that is already installed. Pip-install only the missing packages (pycolmap, gsplat, kornia, …) after the start marker, timing each group. This typically takes about 30 s.
- **COLMAP with CUDA:** install it in-job from conda-forge through micromamba, onto local disk. See `job_skeleton/entry.sh`.

### Cache compiled CUDA extensions on a volume
- Key the cache by (package version, torch + CUDA version, GPU arch).
- Restoring takes about 1–6 s against about 150–190 s for a cold JIT build.
- Use a **fixed** `TORCH_EXTENSIONS_DIR` path, because ninja files hold absolute paths and a changed path silently rebuilds.
- On a cache miss, build in a background thread from t = 0 so the build overlaps the CPU stages.

### Unity Catalog volumes
- **Whole-file writes only.** Appending fails (`Illegal seek`). Rewrite logs whole, or write new chunk files.
- **Rename-over-existing can be refused.** Write `name.tmp`, then rename, falling back to copy + delete.
- **Growing inputs** (a recording still being captured): upload numbered parts that concatenate to the file.
- Keep databases, feature files and training scratch on local disk. The volume holds inputs, published assets and resumable checkpoints.

### Billing
- **List prices** (AWS, at the time of writing; check the current pricing page): A10 about **$2.50/h**, H100 about **$7/h**, 8×H100 about **$56/h**. They appear as DBUs on the Model Training SKU.
- **Queue and provisioning time are not billed.** Billing starts when the GPU attaches. In-job installs, model downloads and extension builds *are* billed, plus a short tail.
- **The run's reported duration includes queue time, so it is not a cost proxy.**
- **Attributing cost to runs:**
  - Billing rows identify the GPU type only by DBU rate.
  - Serverless GPU runs may not carry a joinable job run id. Match by time, and log your own run ids.
- **Typical cost per run at list:**
  - full reconstruction + splat of a 1-minute clip on an A10: about $0.40–0.60;
  - the same on 8×H100: about $5.50;
  - a region paint-in update on an A10: about $0.60–0.70.

### Live telemetry and events into Delta (Zerobus Ingest)
- Pushing telemetry rows (about 5–10 Hz) and job events into Delta tables makes all runs and devices queryable. Keep raw video as files, never in tables.
- **Caveat:** Zerobus accepts OAuth tokens only. A personal access token is refused ("Malformed token"). Use a **service principal** with MODIFY + SELECT on the target tables.
- Keep a local fallback (JSONL with the same columns), so nothing is lost when credentials or the stream fail.

### Which GPU

| shape | use it for | indicative |
|---|---|---|
| 1×A10 (default) | the whole pipeline up to about 250 frames; paint-in | about 10 min, about $0.45 per 1-minute clip |
| 1×H100 | large feed-forward models (VGGT on about 240 frames needs about 32 GB; some models run out of memory on 24 GB beyond about 32 frames) | expected about 1.5× faster than an A10 end to end at about 3× the price; not measured for the full pipeline |
| 8×H100 | lowest latency, with stages pinned to separate GPUs (splat on GPU0, models GPU1, SIFT/mapper GPU2, early splat GPU3) | about 1.8× faster than one A10 at about 13× the cost. CPU-bound stages are not faster |

- **Sharing one GPU has a price.** Running the other stages alongside training slowed the splat by about 15%, the models by about 50% and SIFT by about 80%.
- **Marketplace GPUs:** on the paint-in job, a rented workstation-class Blackwell GPU (96 GB) was about 2.3× faster than an A10 at about half the cost per run, with equal quality.
  - Marketplace costs: image pulls (minutes for 10+ GB images, sometimes failing), SSH and key setup, account 2FA, variable host CPUs. A consumer GPU on a weak CPU host was barely faster than the A10.
  - Managed serverless gives no billing while queued, governed storage and audit; its costs are start-up variance and price.
  - Benchmark your own job on both before choosing.

---

## 4. What doesn't work

| idea | result |
|---|---|
| Feed-forward poses (e.g. VGGT) as the poses of the precise track | About **−8 dB** splat PSNR. Positions were orders of magnitude worse than prior-initialised SIFT BA |
| Feed-forward model + its own tracks + BA | About −4 dB; tracks too few and too noisy |
| Feed-forward poses as the seed for SIFT BA | Converges to the same result (no gain) and registers fewer frames. Good priors are already a better seed. Useful only when priors are missing or bad |
| Feed-forward points as the splat initialisation | About −3 dB at 10k steps, with slower convergence; SfM points win |
| 4K frames instead of 1080p, on the same geometry | No gain. Pose precision, not resolution, is the bottleneck |
| Matching a new clip against photos from very different viewpoints (e.g. ground-level against aerial) | Classical and learned matchers both failed (a handful of inliers, many false accepts). **Rendering the map at the query pose and matching against the render works** |
| Retrieval + feature matching against map photos, with tracking | Low acquisition rate, false accepts that pass the method's own gate, and tracking lost within a few frames |
| MASt3R sparse global alignment on windows longer than about 30 s | Large scale errors (tens of percent) and metre-level camera errors |
| Learned dense SLAM for poses | MASt3R-SLAM is a usable live dense mapper (pose latency about 0.15 s, map latency about 1 s), but its trajectory was no better than GPS/IMU priors. VGGT-SLAM's default updates come only about every 40 s |
| Typed geometric proxies (planes, footprints, crowns) from the first seconds of feed-forward output | The ground plane is roughly right; little else is |
| Exhaustive matching | Half the job's wall time, and a long gap with nothing published |
| Chunked frame selection for offline jobs | About 2 dB lower |
| Per-image pose and appearance optimisation in the splat | Held-out quality drops |
| Rigid Sim3 to drifting priors as a localization gate | It measures prior drift, not localization error |
| Pinning library versions in a managed GPU environment | Very slow, silent starts |
| Appending to files on a UC volume | `Illegal seek` |

---

## 5. Checklist for an agent running this

1. Upload the video and optional priors to a volume. Pick a run id and a run folder.
2. Submit **one** serverless GPU job with `timeout_minutes`, `max_retries: 0` and the base environment. Log the run id.
3. In the job: print a start marker, install only what's missing (timed), restore cached CUDA extensions, preload models in a thread, copy inputs to local disk.
4. Publish the first asset of each kind immediately, then about every 15 s. Write the manifest last.
5. Run QA with pre-registered thresholds, try remediations in parallel, and record the chosen path in the manifest.
6. Exit cleanly with `os._exit`. Afterwards, confirm nothing is still running.
7. Get costs from billing usage × list prices, matched by time. Don't use the job's reported duration.
8. Never tune thresholds to the clip you are testing on. Keep a small regression set of past clips, and only change a default if it improves that set.

## 6. Minimal job skeleton

`job_skeleton/` holds a small, generic version:
- `recon_job.py`: select → predicted or sequential pairs → COLMAP SIFT matching → global or incremental mapper → BA → optional Sim3 to priors → QA → points; optional gsplat training;
- `entry.sh`: in-job COLMAP install;
- `job.yaml`: the serverless GPU job spec.

What has been tested:
- **Locally, on CPU with COLMAP 4.0.4,** on a short 960 px clip: all frames registered at about 0.4 px in seconds, with and without priors. The failure path writes `status: failed`.
- **Not tested:** the GPU and Databricks paths (`entry.sh`, the CUDA COLMAP build, the gsplat stage, masks, volume I/O). Run it once on a short clip before relying on it.

## References (public tools and methods)

| area | references |
|---|---|
| SfM and BA | COLMAP (Schönberger & Frahm, CVPR 2016; GLOMAP-style global mapping in COLMAP 4) |
| Features and matching | SIFT (Lowe, 2004); DISK (Tyszkiewicz et al., 2020); LightGlue (Lindenberger et al., 2023); ALIKED (Zhao et al., 2023); MAGSAC++ (Barath et al., 2020) |
| Gaussian splatting | 3D Gaussian Splatting (Kerbl et al., 2023); gsplat (nerfstudio); Brush |
| Feed-forward 3D | DUSt3R/MASt3R (NAVER LABS Europe); VGGT (Wang et al., 2025); Pi3; Depth Anything V2 and Depth Anything 3 |
| SLAM | MASt3R-SLAM; VGGT-SLAM |
| Segmentation | SegFormer (Xie et al., 2021), ADE20K classes |
| Viewers | PlayCanvas engine and splat-transform (SOG); Spark; Babylon.js |
| Databricks | Serverless GPU / AI Runtime docs; Unity Catalog volumes; system billing tables; Zerobus Ingest |
