# Databricks notebook source
# MAGIC %md
# MAGIC # Load the drone swarm 4D release
# MAGIC
# MAGIC Downloads the release from the Hugging Face dataset (or copies it from a volume folder), puts it in a Unity
# MAGIC Catalog volume, checks every file against the sha256 in `manifest.json`, and writes four Delta tables with
# MAGIC table and column comments: `clips`, `frames`, `telemetry` and `controls`. Safe to re-run: every table is replaced.

# COMMAND ----------

# MAGIC %pip install -q huggingface_hub==2.3.0

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

import hashlib
import json
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor

catalog = dbutils.widgets.get("catalog")  # noqa: F821
schema = dbutils.widgets.get("schema")  # noqa: F821
volume = dbutils.widgets.get("volume")  # noqa: F821
hf_repo = dbutils.widgets.get("hf_repo")  # noqa: F821
hf_revision = dbutils.widgets.get("hf_revision")  # noqa: F821
source_dir = dbutils.widgets.get("source_dir").strip()  # noqa: F821

volume_dir = f"/Volumes/{catalog}/{schema}/{volume}/release"
print("release folder:", volume_dir)

# COMMAND ----------

# The release into the volume: from Hugging Face (public dataset, no token), or from source_dir when given.
if source_dir:
    src = source_dir.rstrip("/")
    print("source:", src)
else:
    from huggingface_hub import snapshot_download

    scratch = "/local_disk0/tmp" if os.access("/local_disk0", os.W_OK) else tempfile.gettempdir()
    src = snapshot_download(hf_repo, repo_type="dataset", revision=hf_revision or None,
                            local_dir=os.path.join(scratch, "drone_swarm_4d"), token=False)
    print(f"source: huggingface.co/datasets/{hf_repo} @ {hf_revision or 'main'}")

if os.path.abspath(src) != os.path.abspath(volume_dir):
    n = 0
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]   # skip the hub's .cache
        rel = os.path.relpath(dirpath, src)
        os.makedirs(os.path.join(volume_dir, rel), exist_ok=True)
        for f in filenames:
            if not f.startswith("."):
                shutil.copyfile(os.path.join(dirpath, f), os.path.join(volume_dir, rel, f))   # whole-file writes
                n += 1
    print(f"copied {n} files")

# COMMAND ----------

# Every file listed in manifest.json must be in the volume with the published size and sha256.
manifest = json.load(open(os.path.join(volume_dir, "manifest.json")))
entries = manifest["files"] if isinstance(manifest, dict) and "files" in manifest else manifest
if isinstance(entries, dict):
    entries = [dict(path=k, **v) for k, v in entries.items()]


def check(e):
    p = os.path.join(volume_dir, e["path"])
    if not os.path.isfile(p):
        return f"missing: {e['path']}"
    h, size = hashlib.sha256(), 0
    with open(p, "rb") as f:
        while b := f.read(8 << 20):
            h.update(b)
            size += len(b)
    if size != int(e["bytes"]) or h.hexdigest() != e["sha256"]:
        return f"mismatch: {e['path']} ({size} bytes)"
    return None


with ThreadPoolExecutor(8) as pool:
    bad = [r for r in pool.map(check, entries) if r]
if bad:
    raise RuntimeError(f"{len(bad)} of {len(entries)} files failed the sha256 check: {bad[:10]}")
print(f"sha256 ok: {len(entries)} files, {sum(int(e['bytes']) for e in entries) / 1e6:.1f} MB")

clip_ids = sorted(d for d in os.listdir(os.path.join(volume_dir, "clips"))
                  if os.path.isfile(os.path.join(volume_dir, "clips", d, "clip.json")))
print("clips:", clip_ids)

# COMMAND ----------

from pyspark.sql import functions as F  # noqa: E402
from pyspark.sql import types as T  # noqa: E402

spark.catalog.setCurrentCatalog(catalog)  # noqa: F821
spark.catalog.setCurrentDatabase(schema)  # noqa: F821

# Each stream of telemetry.parquet goes to one table: `telemetry` (what the drones report) or `controls` (the swarm's
# control loop). Descriptions are from the dataset card; a stream not listed here is placed by its name.
STREAMS = {
    "cam_odom": ("telemetry", "camera odometry, ~50 Hz; cam_x_m/cam_y_m in the drone's own take-off frame, "
                            "alt_rel_m above its take-off point"),
    "attitude": ("telemetry", "drone attitude, 10 Hz"),
    "fc_state": ("telemetry", "flight-controller state, 10 Hz"),
    "radar": ("telemetry", "obstacle radar, 10 Hz"),
    "down_range": ("telemetry", "downward range sensor, ~20 Hz"),
    "exposure": ("telemetry", "camera exposure"),
    "battery": ("telemetry", "battery"),
    "motor_output": ("telemetry", "motor output"),
    "temperatures": ("telemetry", "board temperatures"),
    "wind_fused": ("telemetry", "wind estimate"),
    "rc_sticks": ("telemetry", "RC stick state as reported by the drone"),
    "video_entry": ("telemetry", "live-stream keyframe markers"),
    "detections": ("controls", "on-host person detector that drives the follow, ~8 Hz, 1280x720 detector frame"),
    "control_reference": ("controls", "follow reference sent to each drone's controller, 10 Hz; positions in the swarm's local frame, m"),
    "control_intent": ("controls", "controller output (stick intent), ~50 Hz"),
    "controller_tick": ("controls", "controller loop ticks, ~50 Hz"),
    "control_sent": ("controls", "stick frames sent to each drone, ~125 Hz"),
    "event": ("controls", "events from the flight stack"),
}
CONTROL_HINTS = ("control", "intent", "command", "cmd", "tick", "sent", "event", "plan", "detection")


def family(stream):
    if stream in STREAMS:
        return STREAMS[stream][0]
    return "controls" if any(h in stream.lower() for h in CONTROL_HINTS) else "telemetry"


# Units read from a field-name suffix; ambiguous suffixes (such as _ms: milliseconds or m/s) are left out.
UNITS = {"_m": "m", "_mm": "mm", "_cm": "cm", "_m_s": "m/s", "_deg": "degrees", "_deg_s": "degrees/s", "_s": "s",
         "_pct": "%", "_c": "degrees C", "_dbm": "dBm", "_mah": "mAh", "_ma": "mA", "_hz": "Hz"}


def unit_of(name):
    for suf in sorted(UNITS, key=len, reverse=True):
        if name.lower().endswith(suf):
            return UNITS[suf]
    return None


def sql_text(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


def save(df, name, table_comment, column_comments):
    # FLOAT columns become DOUBLE through their shortest decimal text, so 0.1 stays 0.1 (not 0.10000000149).
    df = df.select([
        F.col(f"`{f.name}`").cast("string").cast("double").alias(f.name) if isinstance(f.dataType, T.FloatType)
        else F.col(f"`{f.name}`") for f in df.schema.fields
    ])
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(name)
    spark.sql(f"COMMENT ON TABLE `{name}` IS '{sql_text(table_comment)}'")  # noqa: F821
    for col in spark.table(name).columns:  # noqa: F821
        text = column_comments.get(col)
        if text:
            spark.sql(f"ALTER TABLE `{name}` ALTER COLUMN `{col}` COMMENT '{sql_text(text)}'")  # noqa: F821
    print(f"{name}: {spark.table(name).count()} rows")  # noqa: F821


# COMMAND ----------

# clips: one row per clip, from clip.json
clip_rows = []
for cid in clip_ids:
    d = os.path.join(volume_dir, "clips", cid)
    c = json.load(open(os.path.join(d, "clip.json")))
    intr = c.get("intrinsics") or {}
    clip_rows.append(dict(
        clip_id=cid, title=c.get("title"), n_drones=int(c.get("n_drones") or len(c["drones"])), drones=list(c["drones"]),
        duration_s=float(c["duration_s"]), fps=float(c["fps"]),
        n_slices=int(c.get("n_slices") or len(c.get("slice_times_s") or [])),
        slice_times_s=[float(t) for t in c.get("slice_times_s") or []],
        frame_of_reference=json.dumps(c.get("frame_of_reference", c.get("frame"))),
        camera_convention=c.get("camera_convention") or (c.get("frame_of_reference") or {}).get("camera_convention"),
        time_base=c.get("time_base"),
        intrinsics={k: {f: float(v[f]) for f in ("width", "height", "fx", "fy", "cx", "cy")} for k, v in intr.items()},
        has_full_res_video=os.path.isdir(os.path.join(d, "video_full")),
        folder=d, clip_json=json.dumps(c),
    ))
intr_t = T.StructType([T.StructField(f, T.DoubleType()) for f in ("width", "height", "fx", "fy", "cx", "cy")])
clips_schema = T.StructType([
    T.StructField("clip_id", T.StringType()), T.StructField("title", T.StringType()), T.StructField("n_drones", T.IntegerType()),
    T.StructField("drones", T.ArrayType(T.StringType())), T.StructField("duration_s", T.DoubleType()),
    T.StructField("fps", T.DoubleType()), T.StructField("n_slices", T.IntegerType()),
    T.StructField("slice_times_s", T.ArrayType(T.DoubleType())), T.StructField("frame_of_reference", T.StringType()),
    T.StructField("camera_convention", T.StringType()), T.StructField("time_base", T.StringType()),
    T.StructField("intrinsics", T.MapType(T.StringType(), intr_t)),
    T.StructField("has_full_res_video", T.BooleanType()), T.StructField("folder", T.StringType()),
    T.StructField("clip_json", T.StringType()),
])
save(spark.createDataFrame(clip_rows, clips_schema), "clips",  # noqa: F821
     "One row per clip of the drone swarm 4D release: a person filmed by a small swarm of drones at once, "
     "rebuilt as a point cloud per time slice. Files are in the volume folder given by `folder`.",
     {"clip_id": "Clip id, also the folder name under clips/ in the release.",
      "title": "Short human-readable title.",
      "n_drones": "Number of drones filming the clip.",
      "drones": "Drone ids (drone_1, drone_2, ...) in the order used everywhere in the release.",
      "duration_s": "Clip length, s.",
      "fps": "Video frame rate, frames per second.",
      "n_slices": "Number of 4D time slices (one point cloud each).",
      "slice_times_s": "Time of each slice, s, on the same clock as frames.t_s and telemetry.t_s.",
      "frame_of_reference": "The world frame of every pose and point (JSON): metric, z up, local to the clip.",
      "camera_convention": "Camera convention of cam_to_world (OpenCV: x right, y down, z forward; row-major 4x4).",
      "time_base": "What t_s means: seconds from slice 0, shared by frames, slices and telemetry.",
      "intrinsics": "Per drone: image width and height (pixels) and pinhole fx, fy, cx, cy (pixels) of the released video.",
      "has_full_res_video": "True when the clip ships the native-resolution video under video_full/.",
      "folder": "Volume folder of the clip's files (videos, masks, clouds, cameras).",
      "clip_json": "The clip's clip.json as published."})

# COMMAND ----------

# frames: one row per drone video frame
frames = None
for cid in clip_ids:
    d = os.path.join(volume_dir, "clips", cid)
    df = (spark.read.parquet(os.path.join(d, "frames.parquet"))  # noqa: F821
          .withColumn("clip_id", F.lit(cid))
          .withColumn("cam_to_world", F.col("cam_to_world").cast("array<double>")))
    df = (df.withColumn("cam_x_m", F.col("cam_to_world")[3]).withColumn("cam_y_m", F.col("cam_to_world")[7])
          .withColumn("cam_z_m", F.col("cam_to_world")[11])
          .withColumn("video_path", F.concat(F.lit(f"{d}/video/"), F.col("drone"), F.lit(".mp4"))))
    frames = df if frames is None else frames.unionByName(df, allowMissingColumns=True)
lead = ["clip_id", "drone", "frame_index", "t_s"]
frames = frames.select(*lead, *[c for c in frames.columns if c not in lead])
save(frames, "frames",
     "One row per video frame per drone: when it was taken and the camera's pose and intrinsics. "
     "frame_index i is frame i of the drone's video (video_path).",
     {"clip_id": "Clip id (clips.clip_id).",
      "drone": "Drone id: drone_1, drone_2, ...",
      "frame_index": "0-based frame number in the drone's video.",
      "t_s": "Time of the frame, s, on the clip clock (same clock as the slices and the telemetry).",
      "cam_to_world": "Camera-to-world pose, row-major 4x4 as 16 numbers, OpenCV camera (x right, y down, z forward), metres.",
      "fx": "Focal length x, pixels.", "fy": "Focal length y, pixels.",
      "cx": "Principal point x, pixels.", "cy": "Principal point y, pixels.",
      "width": "Image width, pixels.", "height": "Image height, pixels.",
      "cam_x_m": "Camera centre x in the clip frame, m (cam_to_world[3]).",
      "cam_y_m": "Camera centre y in the clip frame, m (cam_to_world[7]).",
      "cam_z_m": "Camera centre z in the clip frame, m, z up (cam_to_world[11]).",
      "video_path": "Volume path of the person-masked video this frame belongs to."})

# COMMAND ----------

# telemetry and controls: telemetry.parquet is a sparse wide table (one struct column per stream, set only on that
# stream's rows). Each struct is flattened to <stream>_<field> columns; rows are split by stream family.
base = ["clip_id", "drone", "stream", "seq", "t_s"]
parts = {"telemetry": [], "controls": []}
families = {"telemetry": set(), "controls": set()}
field_notes = {}
for cid in clip_ids:
    df = spark.read.parquet(os.path.join(volume_dir, "clips", cid, "telemetry.parquet")).withColumn("clip_id", F.lit(cid))  # noqa: F821
    for s in [r[0] for r in df.select("stream").distinct().collect()]:
        sub = df.where(F.col("stream") == s)
        cols = [F.col(c) for c in base]
        if s in df.columns and isinstance(df.schema[s].dataType, T.StructType):
            for f in df.schema[s].dataType.fields:
                name = f"{s}_{f.name}"
                cols.append(F.col(f"`{s}`.`{f.name}`").alias(name))
                what = STREAMS.get(s, (None, f"{s} stream"))[1]
                u = unit_of(f.name)
                field_notes[name] = f"{s} ({what}): {f.name}" + (f", {u}" if u else "") + ". NULL on other streams' rows."
        elif s in df.columns:
            cols.append(F.col(f"`{s}`").alias(f"{s}_value"))
            field_notes[f"{s}_value"] = f"Value of the {s} stream. NULL on rows of other streams."
        fam = family(s)
        parts[fam].append(sub.select(*cols))
        families[fam].add(s)
print("streams per table:", {k: sorted(v) for k, v in families.items()})

def reconcile(dfs):
    """Give each column one type across the per-clip, per-stream parts before the union. A stream that is empty
    in one clip can carry a placeholder type there (an all-null field, or an empty list typed as a list of
    integers), so: identical types stay; all-null parts take the others' type; numbers become double; nested
    types take the richest variant (other parts are converted to it through JSON); anything else becomes text."""
    types = {}
    for d in dfs:
        for f in d.schema.fields:
            types.setdefault(f.name, []).append(f.dataType)
    target = {}
    for col, ts in types.items():
        real = [t for t in ts if not isinstance(t, T.NullType)]
        if not real:
            target[col] = T.DoubleType() if unit_of(col) else T.StringType()
        elif all(t == real[0] for t in real):
            target[col] = real[0]
        elif all(isinstance(t, T.NumericType) for t in real):
            target[col] = T.DoubleType()
        elif all(isinstance(t, (T.StructType, T.ArrayType, T.MapType)) for t in real):
            target[col] = ("via_json", max(real, key=lambda t: len(t.simpleString())))
        else:
            target[col] = "text"
    out = []
    for d in dfs:
        cols = []
        for f in d.schema.fields:
            t = target[f.name]
            c = F.col(f"`{f.name}`")
            if t == "text":
                c = F.to_json(c) if isinstance(f.dataType, (T.StructType, T.ArrayType, T.MapType)) else c.cast("string")
            elif isinstance(t, tuple):
                if f.dataType != t[1]:
                    c = c.cast(t[1]) if isinstance(f.dataType, T.NullType) else F.from_json(F.to_json(c), t[1])
            elif f.dataType != t:
                c = c.cast(t)
            cols.append(c.alias(f.name))
        out.append(d.select(*cols))
    print("columns unified through JSON:", sorted(c for c, t in target.items() if isinstance(t, tuple)) or "none",
          "; stored as text:", sorted(c for c, t in target.items() if t == "text") or "none")
    return out


base_notes = {"clip_id": "Clip id (clips.clip_id).", "drone": "Drone id: drone_1, drone_2, ...",
              "stream": "Source stream of the row; only that stream's <stream>_* columns are set.",
              "seq": "Sequence number of the row within its drone and stream.",
              "t_s": "Time, s, on the clip clock (same clock as frames.t_s and the slices)."}
for name, comment in [
    ("telemetry", "What each drone reported during the clip, one row per sample of one stream (pose, attitude, gimbal, "
                  "battery, ...). Columns are <stream>_<field>; on each row only the columns of that row's stream are set."),
    ("controls", "The swarm's control loop during the clip, one row per sample of one stream: the control intent sent to "
                 "each drone, video frames sent, controller ticks and events. Columns are <stream>_<field>; on each row "
                 "only the columns of that row's stream are set."),
]:
    dfs = parts[name]
    if not dfs:
        df = spark.createDataFrame([], "clip_id string, drone string, stream string, seq long, t_s double")  # noqa: F821
    else:
        df = None
        for x in reconcile(dfs):
            df = x if df is None else df.unionByName(x, allowMissingColumns=True)
    df = df.select(*base, *sorted(c for c in df.columns if c not in base)).orderBy("clip_id", "drone", "t_s", "stream", "seq")
    save(df, name, comment, {**base_notes, **field_notes})
