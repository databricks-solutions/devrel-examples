# Databricks notebook source
# MAGIC %md
# MAGIC # Load release 0
# MAGIC
# MAGIC Copies the release files (`flights`, `telemetry`, `landings` and `blended_wind_reference` parquet) into a
# MAGIC Unity Catalog volume and writes them as Delta tables with table and column comments. Safe to re-run: every
# MAGIC table is replaced.

# COMMAND ----------

import os
import shutil

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
source_dir = dbutils.widgets.get("source_dir")

volume_dir = f"/Volumes/{catalog}/{schema}/{volume}/release0"
TABLES = ["flights", "telemetry", "landings", "blended_wind_reference"]

# COMMAND ----------

# The release files into the volume (skipped when source_dir already is that folder).
os.makedirs(volume_dir, exist_ok=True)
for name in TABLES:
    src = os.path.join(source_dir, f"{name}.parquet")
    dst = os.path.join(volume_dir, f"{name}.parquet")
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copyfile(src, dst)
    print(f"{dst}: {os.path.getsize(dst)} bytes")

# COMMAND ----------

TABLE_COMMENTS = {
    "flights": "One row per flight of a sub-250 g consumer quadcopter (13 flights: 7 flown for wind, 6 autonomous "
               "charging-dock landing cycles). Anonymised: hashed ids, anonymised sites, no absolute time or position.",
    "telemetry": "One row per flight-controller sample (about every 0.1 s) per flight. Positions in a local frame about the take-off point "
                 "(x north, y east, z up); velocities north, east, down; angles in degrees; wind directions are "
                 "the direction the wind blows FROM, clockwise from north.",
    "landings": "One row per autonomous landing attempt on the charging dock.",
    "blended_wind_reference": "Reference answer, kept apart from the raw telemetry: the blended wind for each "
                              "telemetry sample (joins telemetry on flight_id, t_s).",
}

COLUMN_COMMENTS = {
    "flights": {
        "flight_id": "Flight id (keyed hash).",
        "site": "Anonymised take-off site: site_1, site_2, ...",
        "session": "Day of flying: day_1, day_2, ... in date order.",
        "kind": "manual | automated_manoeuvres | system_identification | autonomous_dock_cycle",
        "duration_s": "Motors-on time, s.",
        "airborne_s": "Time with the motors on and at least 0.3 m above take-off, s.",
        "samples": "Telemetry rows for this flight.",
        "has_live_blended_wind": "True if this flight's rows in blended_wind_reference were recorded live; false if "
                                 "they were computed afterwards by the published reference implementation.",
        "ends_in": "How the flight ended: hand_catch | dock_landing | ground_landing | unknown. "
                   "A hand catch is not a landing.",
    },
    "telemetry": {
        "flight_id": "Flight id (keyed hash).",
        "t_s": "Time since the flight's first sample, s.",
        "motors_on": "True while the motors run.",
        "flight_phase": "on_ground | taking_off | in_air | landing",
        "pos_x_m": "Flight controller estimated position north of the take-off point, m.",
        "pos_y_m": "Flight controller estimated position east of the take-off point, m.",
        "pos_z_m": "Height above the take-off point (barometric altitude minus its take-off value), m, z up.",
        "yaw_deg": "Estimated yaw of the pose, degrees.",
        "height_above_surface_m": "Downward range sensor: height above whatever is below, m. NULL when out of range.",
        "vel_north_mps": "Ground velocity north, m/s (flight controller).",
        "vel_east_mps": "Ground velocity east, m/s (flight controller).",
        "vel_down_mps": "Ground velocity down, m/s (flight controller; positive = descending).",
        "pitch_deg": "Body pitch, degrees (positive = nose up).",
        "roll_deg": "Body roll, degrees (positive = right side down).",
        "heading_deg": "Compass heading of the nose, degrees clockwise from north, in [0, 360).",
        "fc_wind_speed_mps": "The flight controller's own wind speed estimate, m/s, in 0.1 m/s steps; "
                             "0 on the ground.",
        "fc_wind_from_deg": "The flight controller's own wind direction (FROM, clockwise from north), "
                            "only in 45 degree sectors: 0, 45, ..., 315. NULL when it reports none.",
        "battery_pct": "Battery state of charge, %.",
        "battery_v": "Battery voltage, V.",
        "battery_a": "Battery current, A (negative = discharging).",
        "stick_roll": "Commanded roll stick, -1..1.",
        "stick_pitch": "Commanded pitch stick, -1..1.",
        "stick_yaw": "Commanded yaw stick, -1..1.",
        "stick_throttle": "Commanded throttle stick, -1..1.",
    },
    "landings": {
        "landing_id": "Dock landing attempt id (keyed hash).",
        "flight_id": "Flight id (keyed hash).",
        "t_commit_s": "When the aircraft committed to the final descent, s since the flight's first sample.",
        "outcome": "seated | not_seated",
        "approach": "Approach flown to the dock (spiral).",
        "commit_error_cm": "Horizontal error to the dock seat at the commit, averaged over the gate window, cm.",
        "commit_heading_error_deg": "Heading error to the dock seat at the commit, degrees.",
        "commit_speed_cmps": "Speed over the gate window before the commit, cm/s.",
        "low_hold_s": "Time spent in the low hold over the dock before the commit, s.",
        "retries": "Climbs back for another descent when the gate was not met within 20 s.",
        "contact_samples": "Battery samples the dock read through its contacts after touchdown "
                           "(0 when not seated).",
    },
    "blended_wind_reference": {
        "flight_id": "Flight id (keyed hash).",
        "t_s": "Time since the flight's first sample, s (the telemetry sample).",
        "blended_wind_speed_mps": "Blended wind speed, m/s: the flight controller's speed.",
        "blended_wind_from_deg": "Blended wind direction (FROM, degrees clockwise from north): the flight "
                                 "controller's 45 degree sector refined by the body tilt in steady flight, kept "
                                 "within +/-22.5 degrees of the sector centre.",
        "blended_wind_source": "blended when the tilt refined the direction; fc when the flight controller's "
                               "sector direction is used as is.",
        "blended_wind_quality": "Share (0-1) of the last 5 s of samples steady enough to refine the direction.",
    },
}

# COMMAND ----------

spark.catalog.setCurrentCatalog(catalog)
spark.catalog.setCurrentDatabase(schema)


def sql_text(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


for name in TABLES:
    df = spark.read.parquet(f"{volume_dir}/{name}.parquet")
    # FLOAT columns become DOUBLE through their shortest decimal text, so 435.3 stays 435.3 (not 435.299988).
    df = df.select([
        df[f.name].cast("string").cast("double").alias(f.name) if f.dataType.typeName() == "float" else df[f.name]
        for f in df.schema.fields
    ])
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(name)
    spark.sql(f"COMMENT ON TABLE `{name}` IS '{sql_text(TABLE_COMMENTS[name])}'")
    for col, text in COLUMN_COMMENTS[name].items():
        spark.sql(f"ALTER TABLE `{name}` ALTER COLUMN `{col}` COMMENT '{sql_text(text)}'")
    print(name, spark.table(name).count(), "rows")
