# Data

The release is not stored in this repository. It lives on Hugging Face as the public dataset
[`nick-karpov/drone-swarm-4d`](https://huggingface.co/datasets/nick-karpov/drone-swarm-4d); the dataset card there describes every file, stream and column, the clock, the frames of reference and the method.

The load job (`src/load_release.py`) downloads it with `huggingface_hub.snapshot_download` (no token needed), copies it into the volume as `/Volumes/<catalog>/<schema>/release_files/release/`, and checks every file against the sha256 in `manifest.json` before it writes any table.

## Layout

```
README.md                         the dataset card
manifest.json                     every file: path, bytes, sha256
clips/<clip_id>/                  clip1_three_drones (3 drones, 10 s, 1080p), walk_4k (2 drones, 8 s, 4K source)
  clip.json                       drones, timing, frame of reference, slice times, intrinsics, camera convention
  cameras.json                    per slice and drone: cam_to_world 4x4 (row-major, 16 floats, OpenCV camera)
  frames.parquet                  one row per drone frame: drone, frame_index, t_s, cam_to_world, fx, fy, cx, cy, width, height
  telemetry.parquet               every telemetry and control stream: drone, stream, seq, t_s, one struct column per stream
  video/<drone>.mp4               person-masked video, H.264, at most 1920x1080; frame i = frames.parquet frame_index i
  video_full/<drone>.mp4          walk_4k only: person-masked video at native 4K, H.265
  masks/<drone>.mkv               the keep mask, lossless FFV1 gray (255 = person)
  cloud/index.json                slice list [{i, t_s, file, n}] and bounds
  cloud/sNNN.bin                  the person's points for slice NNN: int16 x, y, z in mm, then uint8 r, g, b (9 bytes per point, little-endian)
```

## Where each part goes on Databricks

| Release | Databricks |
|---|---|
| `clip.json` | table `clips` (with the file as published in `clip_json`) |
| `frames.parquet` | table `frames` |
| `telemetry.parquet` | tables `telemetry` (what the drones report) and `controls` (the swarm's control loop), flattened to `<stream>_<field>` |
| videos, masks, `cameras.json`, clouds | files in the volume, read by the App and by the rebuild job |

Your rebuilt moments are written next to the release, as `/Volumes/<catalog>/<schema>/release_files/rebuilds/<clip_id>/sNNN.bin` (same 9-byte format) and `sNNN.json` (settings and comparison).
