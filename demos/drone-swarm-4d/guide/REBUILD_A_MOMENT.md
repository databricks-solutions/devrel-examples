# Rebuild one moment

Pick an instant of a clip, give every drone's picture of it to Pi3X on a serverless GPU, and get your own 3D person for that instant, in the release's frame, next to the published one in the App.

The release was made the same way at every slice: [Pi3X](https://github.com/yyfz/Pi3) solved the drones' synchronised views jointly, and the result was put into a metric frame through the drones' poses, then merged without seams and smoothed in time. This guide runs the core of that for one slice, in one small job (`rebuild/rebuild_moment.py`), so you can see each step and change it.

## What the job does

```
volume: release/clips/<clip>/                                  volume: rebuilds/<clip>/
  cloud/index.json   ─► the slice nearest your time               sNNN.bin   the person (9 bytes per point)
  frames.parquet     ─► each drone's frame at that time           sNNN.json  settings, alignment, comparison
  video/, masks/     ─► that frame and its person mask
  cameras.json       ─► each drone's pose at that slice
                          │
ONE serverless GPU job:   inputs ─► Pi3X ─► align ─► person ─► compare ─► write
```

1. **Inputs.** The slice nearest `--t` in `cloud/index.json`. For each drone, the frame of `frames.parquet` nearest that slice time (frame *i* of `video/<drone>.mp4` is `frame_index` *i*), decoded exactly, with the same frame of `masks/<drone>.mkv`, the released intrinsics scaled to the video's size, and the drone's `cam_to_world` from `cameras.json`.
2. **Pi3X.** All views of the instant in one forward pass, at about 672×378 (Pi3X's default size; its patches are 14 pixels). By default Pi3X is *conditioned* on the released intrinsics and poses (`--condition poses`): it still predicts its own cameras and a point map per view, but starts from the known geometry. `--condition intrinsics` and `--condition none` give it less.
3. **Align.** Pi3X answers in its own frame and scale. A similarity transform (Sim(3)) maps its cameras onto the released ones: the rotation first (the chordal mean of the per-camera rotation differences), then scale and translation from the camera centres. The same transform puts the points in the clip frame, in metres. The report keeps how far each aligned camera ended up from the released one.
4. **Person.** In each view, the pixels inside the person mask (eroded by one model pixel), minus depth edges (where the log depth jumps) and minus anything more than 1 m from the person's median depth. The point map is upsampled ×2 first, and colours come from the full-size frame. Where two drones see the same surface within 4 cm, the points meet in the middle (`--fuse-cm`).
5. **Compare.** Nearest-neighbour distances from your points to the released slice and back, in cm, and the Chamfer distance (the mean of the two means). Rebuild-to-release says how close your surface lies to the published one; release-to-rebuild also counts what your single instant missed.
6. **Write.** `rebuilds/<clip>/sNNN.bin` (the release's cloud format: int16 x, y, z in mm, then uint8 r, g, b) and `sNNN.json`, each written whole and then renamed into place (volumes cannot append).

The job logs a start marker, then one line as each stage starts and ends, and exits non-zero on any error. A watchdog stops it after `--timeout-s`, in addition to the job's own `timeout_minutes`.

## Before you start

- The bundle is deployed and `load_release` has run: the release is in `/Volumes/<catalog>/<schema>/release_files/release/`.
- **Serverless GPU compute (AI Runtime)** is enabled for the workspace, and you can submit jobs with the `air` CLI (or `databricks air`), authenticated with a profile.
- `WRITE VOLUME` on `release_files` (you created it, so you have it).
- Outbound internet from the job: it installs Pi3's code (pinned to a commit) and downloads the Pi3X weights (about 5.4 GB, pinned to a revision) from Hugging Face.

## 1. Pick a moment

Play the clip in the App and note the time readout, or look at the slices in SQL:

```sql
SELECT clip_id, n_drones, duration_s, n_slices, slice_times_s[150] AS t_of_slice_150
FROM <catalog>.drone_swarm_4d.clips;
```

A moment where the drones see the person from well-separated sides gives the most to compare. Camera elevations at a time come straight from `frames`:

```sql
SELECT drone, t_s, cam_z_m
FROM <catalog>.drone_swarm_4d.frames
WHERE clip_id = 'clip1_three_drones' AND abs(t_s - 4.0) < 0.02;
```

## 2. Fill in the job

In `rebuild/job.yaml`, replace the placeholders:

- `<workspace-folder>`: a workspace folder for the MLflow experiment, e.g. `/Users/<you>`;
- `<run_name>`: anything, e.g. `clip1-t4`;
- in `command`: `<catalog>`, `<schema>`, and the clip and time (`--clip clip1_three_drones --t 4.0`).

Options you can add to `command`:

| option | default | what |
|---|---|---|
| `--t SECONDS` or `--slice N` | | the moment: a time on the clip clock, or a slice position |
| `--condition` | `poses` | what Pi3X gets besides the images: `poses` (intrinsics and poses), `intrinsics`, `none` |
| `--res WxH` | about 672 on the long side | Pi3X input size, multiples of 14 |
| `--up` | 2 | point-map upsampling before the person is cut out |
| `--min-conf` | 0 | drop pixels below this Pi3X confidence (0..1) |
| `--fuse-cm` | 4 | cross-drone midpoint fusion radius; 0 turns it off |

## 3. Submit

```bash
cd demos/drone-swarm-4d/rebuild
air run --file job.yaml -p <profile>      # or: databricks air run --file job.yaml -p <profile>
```

The job runs on one A10 (`GPU_1xA10`), the smallest shape, which has room for Pi3X in bf16 with three views. Queue and provisioning time are not billed; installs, the weights download and the run are.

## 4. Follow it

In the run's output you should see, in order:

```
JOB_START hh:mm:ss                              the platform has started your code
setup: torch ... cuda True
setup: done in ... s                            Pi3 installed, packages checked
[    0.0s] rebuild clip1_three_drones t=4.0 slice=None model=pi3x device=cuda
[    ...s] stage inputs: start
[    ...s] drone_1: frame ... at ...s (slice ...s), 1920x1080, mask ...%     one line per drone
[    ...s] stage model: start                    the weights download, once per run
[    ...s] Pi3X bb1deea4 on cuda, ... GiB
[    ...s] stage infer: start
[    ...s] Sim(3) scale ...; camera rotation error [...] deg, centre error [...] cm
[    ...s] drone_1: ... person points                                        one line per drone
[    ...s] ... points (release ...), Chamfer ... cm
[    ...s] wrote /Volumes/.../rebuilds/clip1_three_drones/sNNN.bin and .json
```

The last line of output is a one-line JSON summary: the point count, the comparison and the seconds per stage.

## 5. See it in the App

Reload the App and pick the clip. A *Release / Your rebuild / Both* switch appears in the 4D view, with a tick on the timeline at your moment:

- **Your rebuild** jumps to the moment and shows your cloud in place of the release;
- **Both** draws yours in one flat orange over the release, so you can see where the surfaces agree and where they part;
- the caption gives your point count and the Chamfer distance to the release.

The App lists every `sNNN.bin` in `rebuilds/<clip>/`, so several moments can sit side by side; it shows the first.

## 6. Read the report

`rebuilds/<clip>/sNNN.json`:

| field | what |
|---|---|
| `slice`, `t_s`, `views` | the moment, and each drone's frame index and time |
| `model` | `yyfz233/Pi3X` and its revision, the conditioning, the input size and device |
| `alignment.scale` | Pi3X units to metres for this instant |
| `alignment.camera_rotation_error_deg`, `camera_centre_error_cm` | per drone, how far Pi3X's own camera ended up from the released one after the Sim(3) |
| `n_points`, `n_per_drone`, `n_fused` | your cloud, and how much of it each drone contributed |
| `comparison.chamfer_cm` | the Chamfer distance to the released slice |
| `comparison.rebuild_to_release_cm`, `release_to_rebuild_cm` | mean, median and 90th percentile of the distances each way |
| `comparison.within_2cm` | the share of each cloud within 2 cm of the other |
| `seconds` | time per stage |

Read it into a table with SQL:

```sql
SELECT clip, slice, t_s, n_points, comparison.chamfer_cm, alignment.camera_centre_error_cm
FROM read_files('/Volumes/<catalog>/drone_swarm_4d/release_files/rebuilds/*/*.json', format => 'json', multiLine => true);
```

## Things to try

- **Give Pi3X less.** Run the same moment with `--condition intrinsics` and `--condition none`, and compare `camera_rotation_error_deg` and `chamfer_cm`. With nothing given, the camera error measures how well Pi3X recovers the swarm's geometry from the pictures alone.
- **The two-drone clip.** `--clip walk_4k`: two drones, one of them climbing until it looks down at the person from more than 60°.
- **No fusion.** `--fuse-cm 0` keeps every drone's surface as it came out of the model.
- **Higher resolution.** `--res 1008x560` gives Pi3X more pixels; compare the report with the default.

## Run it on your laptop

`rebuild_moment.py` also runs outside Databricks against a local copy of the release, on CPU or Apple silicon (`--device cpu` or `mps`). Two ways:

- **The plumbing only, in seconds:** `--model stub` swaps Pi3X for a stand-in that renders depth from the released slice in a deliberately different frame and scale. Everything else runs for real: decoding, masks, the Sim(3), the person cut, fusion, the comparison and the files. The stand-in's cloud lands on the released surface (rebuild-to-release median under a centimetre), which checks the geometry end to end.

  ```bash
  pip install numpy opencv-python-headless scipy pyarrow
  python rebuild/rebuild_moment.py --release /path/to/drone-swarm-4d --clip clip1_three_drones --t 4.0 \
      --out ./rebuilds --model stub --device cpu
  ```

- **With Pi3X:** install PyTorch and Pi3 (`pip install "pi3 @ https://github.com/yyfz/Pi3/archive/9fa3ddb3f8d53041f8b2738df404f62223bbaa7b.tar.gz" safetensors huggingface_hub`) and drop `--model stub`. The model needs about 6 GB of memory in fp32.

To see local rebuilds in the App, run it with `DRONE4D_REBUILD_DIR=./rebuilds` next to `DRONE4D_LOCAL_DIR`.

## Files

| file | what |
|---|---|
| `rebuild/job.yaml` | the serverless GPU job: A10, a timeout, no retries, the base AI environment |
| `rebuild/entry.sh` | in-job setup: Pi3 at a pinned commit, plus any missing package at a pinned version; then the job |
| `rebuild/rebuild_moment.py` | the job: inputs, Pi3X, Sim(3), person, comparison, files |
