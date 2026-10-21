# Derive the blended wind yourself, in Genie

The release ships a reference column, `blended_wind_from_deg`, in the `blended_wind_reference` table. This guide
rebuilds it from the raw `telemetry` columns, step by step, inside the Genie space that the bundle creates. At the
end you compare your result with the reference. The Genie space does not include the reference table, so that
last step runs in the SQL editor.

**What you need.** The bundle in this example ([`../README.md`](../README.md)) is deployed and its load job has run.
You use the Genie space "Quadcopter Flight Telemetry".

**How to use this guide.** Ask the prompts in order, in one Genie conversation. Each step adds one stage to the
same query. Under each prompt is the SQL Genie should arrive at.
- Genie writes table names in full (`<catalog>.<schema>.telemetry`); here they are written short.
- Genie's SQL may differ in form. Compare the numbers, not the text.
- Genie only runs SELECT queries, so every stage is a common table expression (CTE) in one `WITH` query.
- If Genie goes astray, paste the SQL into the chat ("run this SQL"). You can also run it in the SQL editor after
  `USE CATALOG <catalog>; USE SCHEMA <schema>;`.

The complete query is at the end.

**Status.** Every SQL block below was run with open-source Apache Spark 4.0.1 on the release 0 parquet files.
- The result matches the shipped column: median difference 0.02°, 99.7 % of samples within 1°. The full numbers are
  in step 5.
- The complete query was also run on a Databricks SQL warehouse: the same result to rounding (step 5).
- The step-by-step prompts have **not** been run in Genie. Prompt wording and Genie's own SQL are untested.

---

## Why a blended wind

The flight controller estimates the wind itself.
- `fc_wind_speed_mps`: its speed, in 0.1 m/s steps.
- `fc_wind_from_deg`: its direction, **only in 45° sectors** (0, 45, …, 315). In a wind from about 20°, the
  reading flips between N (0) and NE (45) several times a minute.

The aircraft's tilt carries the missing information.
- In steady flight a multirotor leans into the air moving past it. Its pitch and roll balance the drag of its
  air-relative velocity.
- Invert that balance and you get the air-relative velocity. Ground velocity minus air-relative velocity is the
  wind.

The blended wind combines the two:
- **speed:** the flight controller's;
- **direction:** the tilt's, low-passed and kept inside the controller's own sector (±22.5° about the sector
  centre).

The method is the published reference implementation's. The constants below are its fitted drag model for this
aircraft.

Frames used throughout:
- `vel_north_mps` and `vel_east_mps` are ground velocity in the world frame.
- `heading_deg` is clockwise from north.
- `pitch_deg` is positive nose up. `roll_deg` is positive right side down.
- Wind *from* directions point to where the air comes from.
- Inside the calculation the wind is a vector (north, east) pointing where the air moves **to**.

> **Prompt 0.** *For the gustiest flight, how often does the flight controller's wind direction change sector,
> and which sectors does it use?*

Genie should count `fc_wind_from_deg` values in `telemetry` for that flight: N and NE, roughly half each, changing
sector about 6 times a minute.

---

## Step 1: steady samples

The method uses only samples where the aircraft is close to steady.
- Each sample is compared with the sample **8 rows earlier**, about 0.8 s at 10 Hz.
- That span must last 0.5 to 1.2 s.
- Over the span, the ground acceleration must be at most **1 m/s²** and the yaw rate at most **30 °/s**.
- The tilt is read at the **middle** of the span, 4 rows earlier.
- Only motors-on samples with all inputs present count. The numbering skips the others.

> **Prompt 1.** *From telemetry, keep the samples with the motors on where the flight controller wind speed,
> velocities, heading, pitch and roll are all present, and number them in time order per flight. For each
> sample, look back 8 rows (and 4 rows for the middle of the span). Keep spans of 0.5 to 1.2 s. Compute the
> north and east acceleration over the span and the yaw rate, wrapping the heading change into −180…180. A sample
> is steady when the acceleration magnitude is at most 1 m/s² and the absolute yaw rate at most 30 °/s. Show the
> steady share per flight.*

<!-- cte -->
```sql
samples AS (
  SELECT
    flight_id, t_s, vel_north_mps AS vn, vel_east_mps AS ve, heading_deg, pitch_deg, roll_deg,
    fc_wind_speed_mps, fc_wind_from_deg,
    ROW_NUMBER() OVER (PARTITION BY flight_id ORDER BY t_s) AS n
  FROM telemetry
  WHERE motors_on
    AND fc_wind_speed_mps IS NOT NULL
    AND vel_north_mps IS NOT NULL AND vel_east_mps IS NOT NULL AND vel_down_mps IS NOT NULL
    AND heading_deg IS NOT NULL AND pitch_deg IS NOT NULL AND roll_deg IS NOT NULL
),
spans AS (
  SELECT
    s.*,
    LAG(t_s, 8) OVER w AS t_a, LAG(vn, 8) OVER w AS vn_a, LAG(ve, 8) OVER w AS ve_a,
    LAG(heading_deg, 8) OVER w AS h_a,
    LAG(t_s, 4) OVER w AS t_m, LAG(vn, 4) OVER w AS vn_m, LAG(ve, 4) OVER w AS ve_m,
    LAG(heading_deg, 4) OVER w AS h_m, LAG(pitch_deg, 4) OVER w AS pitch_m, LAG(roll_deg, 4) OVER w AS roll_m
  FROM samples s
  WINDOW w AS (PARTITION BY flight_id ORDER BY n)
),
spans_ok AS (
  SELECT
    *,
    (vn - vn_a) / (t_s - t_a) AS acc_n,
    (ve - ve_a) / (t_s - t_a) AS acc_e,
    (PMOD(heading_deg - h_a + 180, 360) - 180) / (t_s - t_a) AS yaw_rate_dps
  FROM spans
  WHERE t_a IS NOT NULL AND t_s - t_a >= 0.5 AND t_s - t_a < 1.2
),
steady AS (
  SELECT * FROM spans_ok WHERE HYPOT(acc_n, acc_e) <= 1.0 AND ABS(yaw_rate_dps) <= 30
)
```

<!-- check -->
```sql
SELECT
  s.flight_id,
  COUNT(*) AS spans,
  ROUND(AVG(CASE WHEN HYPOT(s.acc_n, s.acc_e) <= 1.0 AND ABS(s.yaw_rate_dps) <= 30 THEN 1.0 ELSE 0.0 END), 2)
    AS steady_share
FROM spans_ok s
GROUP BY s.flight_id
ORDER BY steady_share DESC
```

Expect a steady share between about 0.6 and 0.99 per flight. The flights with the most manoeuvring sit lowest.

---

## Step 2: the wind the tilt implies

For each steady sample, take the middle of its span.

1. Rotate the ground acceleration into the body frame (forward, right) with the heading ψ:
   `a_fwd = cos ψ·a_n + sin ψ·a_e`, `a_right = −sin ψ·a_n + cos ψ·a_e`.
2. Compute the specific force the tilt says the drag must supply, less the tilt bias and the acceleration:
   - `y_fwd = −g·tan(pitch) − bias_fwd − a_fwd`
   - `y_right = g·tan(roll)/cos(pitch) − bias_right − a_right`
   - with `g = 9.81`, `bias = (−0.13491, 0.00804)` m/s².
3. Invert the drag model `y_k = air_k·(c1_k + c2_k·|air|)` for the air-relative velocity:
   - `c1 = (0.35408, 0.49623)` per s, `c2 = (0.02293, 0.01954)` per m;
   - solve by 12 fixed-point iterations from zero (`AGGREGATE` over `SEQUENCE(1, 12)`).
4. Rotate the air-relative velocity back to north/east and subtract it from the ground velocity. The result is the
   wind, as the vector the air moves **to**.

> **Prompt 2.** *For each steady sample, at the middle of its span: rotate the acceleration into body axes using
> the heading. Compute y_fwd = −9.81·tan(pitch) + 0.13491 − a_fwd and y_right = 9.81·tan(roll)/cos(pitch) −
> 0.00804 − a_right. Solve air_fwd = y_fwd / (0.35408 + 0.02293·|air|) and air_right = y_right / (0.49623 +
> 0.01954·|air|) by 12 fixed-point iterations starting at zero. Rotate air back to north/east and subtract it from
> the ground velocity to get the tilt wind (north, east). Per flight, compare its mean speed with the flight
> controller's mean wind speed.*

<!-- cte -->
```sql
tilt AS (
  SELECT
    flight_id, n, t_m, fc_wind_speed_mps,
    vn_m - (COS(RADIANS(h_m)) * air.x - SIN(RADIANS(h_m)) * air.y) AS tilt_n,
    ve_m - (SIN(RADIANS(h_m)) * air.x + COS(RADIANS(h_m)) * air.y) AS tilt_e
  FROM (
    SELECT
      *,
      AGGREGATE(
        SEQUENCE(1, 12),
        NAMED_STRUCT('x', CAST(0 AS DOUBLE), 'y', CAST(0 AS DOUBLE)),
        (a, i) -> NAMED_STRUCT(
          'x', y_fwd / (0.35408 + 0.02293 * HYPOT(a.x, a.y)),
          'y', y_right / (0.49623 + 0.01954 * HYPOT(a.x, a.y)))) AS air
    FROM (
      SELECT
        *,
        -9.81 * TAN(RADIANS(pitch_m)) - (-0.13491)
          - (COS(RADIANS(h_m)) * acc_n + SIN(RADIANS(h_m)) * acc_e) AS y_fwd,
        9.81 * TAN(RADIANS(roll_m)) / COS(RADIANS(pitch_m)) - 0.00804
          - (-SIN(RADIANS(h_m)) * acc_n + COS(RADIANS(h_m)) * acc_e) AS y_right
      FROM steady
    ) balance
  ) inverted
)
```

<!-- check -->
```sql
SELECT
  flight_id,
  COUNT(*) AS steady_samples,
  ROUND(AVG(HYPOT(tilt_n, tilt_e)), 2) AS tilt_wind_speed_mps,
  ROUND(AVG(fc_wind_speed_mps), 2) AS fc_wind_speed_mps,
  ROUND(PMOD(DEGREES(ATAN2(-AVG(tilt_e), -AVG(tilt_n))), 360), 0) AS tilt_wind_from_deg
FROM tilt
GROUP BY flight_id
ORDER BY fc_wind_speed_mps DESC
```

On the four windiest flights the tilt wind speed comes out at about 3 m/s, within about 0.15 m/s of the
controller's. Its mean direction is a little east of north (13° to 23°). Near the ground (the dock cycles, under
0.5 m/s) the tilt wind is mostly noise.

---

## Step 3: smooth it

A single sample's tilt is noisy, so the reference low-passes the tilt wind over the steady samples:
- each update is `f ← f + k·(w − f)` with `k = Δt / 3 s`, where Δt is the time since the previous steady sample;
- after a gap of 3 s or more (`k` would reach 1), it restarts from the new sample.

That is a recursion, and SQL has no loops. It unrolls into running sums:
- `f_n = P_n · Σ_j k_j·w_j / P_j`, where `P_n = Π (1 − k_i)` is a running product. Take `k = 1` at a restart.
- The running product is `EXP(SUM(LN(1 − k)))`.
- The result is exact, not an approximation.

> **Prompt 3.** *Low-pass the tilt wind per flight over the steady samples: f = f + k·(w − f) with k = (time since
> the previous steady sample) / 3 s, restarting from the sample itself when that gap is 3 s or more. Write the
> recursion with running sums: a restart counter as the segment, the running sum of LN(1 − k) as log_keep_sum, and
> f = EXP(log_keep_sum) × running SUM(k × EXP(−log_keep_sum) × w), with k = 1 at a restart.*

<!-- cte -->
```sql
smooth_k AS (
  SELECT
    *,
    CASE WHEN LAG(t_m) OVER w IS NULL OR t_m - LAG(t_m) OVER w >= 3 THEN 1 ELSE 0 END AS restart,
    LEAST((t_m - LAG(t_m) OVER w) / 3.0, 1.0) AS k
  FROM tilt
  WINDOW w AS (PARTITION BY flight_id ORDER BY n)
),
smooth_seg AS (
  SELECT
    *,
    SUM(restart) OVER (PARTITION BY flight_id ORDER BY n ROWS UNBOUNDED PRECEDING) AS segment,
    CASE WHEN restart = 1 THEN 1.0 ELSE k END AS weight,
    CASE WHEN restart = 1 THEN 0.0 ELSE LN(1 - k) END AS log_keep
  FROM smooth_k
),
smooth AS (
  SELECT
    flight_id, n, t_m,
    EXP(log_keep_sum) * SUM(weight * EXP(-log_keep_sum) * tilt_n) OVER seg AS lp_n,
    EXP(log_keep_sum) * SUM(weight * EXP(-log_keep_sum) * tilt_e) OVER seg AS lp_e
  FROM (
    SELECT *, SUM(log_keep) OVER seg AS log_keep_sum
    FROM smooth_seg
    WINDOW seg AS (PARTITION BY flight_id, segment ORDER BY n ROWS UNBOUNDED PRECEDING)
  ) c
  WINDOW seg AS (PARTITION BY flight_id, segment ORDER BY n ROWS UNBOUNDED PRECEDING)
)
```

<!-- check -->
```sql
SELECT
  flight_id,
  COUNT(*) AS steady_samples,
  ROUND(AVG(HYPOT(lp_n, lp_e)), 2) AS smoothed_speed_mps,
  ROUND(PMOD(DEGREES(ATAN2(-AVG(lp_e), -AVG(lp_n))), 360), 0) AS smoothed_from_deg
FROM smooth
GROUP BY flight_id
ORDER BY smoothed_speed_mps DESC
```

---

## Step 4: constrain it to the controller's sector

The final direction is computed at every motors-on sample.

1. Take the latest smoothed tilt wind at or before the sample.
2. Use it only if all of these hold:
   - it is **fresh**: less than 5 s since its steady sample's middle;
   - it is at least **0.3 m/s**;
   - the controller reports a speed above 0 and a sector.
3. Compute how far its *from* direction is from the controller's sector, wrapped into −180…180.
4. Clamp that offset to **±22.5°** and add it to the sector.

Otherwise the direction is the controller's sector, which the shipped data marks `blended_wind_source = 'fc'`. The
speed is always the controller's.

> **Prompt 4.** *At every sample from step 1, take the latest smoothed tilt wind at or before it (ignore nulls). If
> it is less than 5 s old, at least 0.3 m/s, and the controller reports a speed above 0 and a sector: take the tilt
> wind's from-direction (DEGREES(ATAN2(−east, −north)) modulo 360), its offset from fc_wind_from_deg wrapped into
> −180…180, clamped to ±22.5°, and add that to fc_wind_from_deg (modulo 360). Call it my_blended_from_deg. Show,
> per flight, the share of samples refined this way and the circular mean of my_blended_from_deg.*

<!-- cte -->
```sql
latest AS (
  SELECT
    s.*,
    LAST_VALUE(m.t_m, TRUE) OVER w AS tilt_t,
    LAST_VALUE(m.lp_n, TRUE) OVER w AS tilt_n,
    LAST_VALUE(m.lp_e, TRUE) OVER w AS tilt_e
  FROM samples s
  LEFT JOIN smooth m ON m.flight_id = s.flight_id AND m.n = s.n
  WINDOW w AS (PARTITION BY s.flight_id ORDER BY s.n ROWS UNBOUNDED PRECEDING)
),
derived AS (
  SELECT
    *,
    CASE
      WHEN tilt_t IS NOT NULL AND t_s - tilt_t < 5 AND HYPOT(tilt_n, tilt_e) >= 0.3
           AND fc_wind_speed_mps > 0 AND fc_wind_from_deg IS NOT NULL
      THEN PMOD(fc_wind_from_deg + GREATEST(-22.5, LEAST(22.5,
             PMOD(DEGREES(ATAN2(-tilt_e, -tilt_n)) - fc_wind_from_deg + 180, 360) - 180)), 360)
    END AS my_blended_from_deg
  FROM latest
)
```

<!-- check -->
```sql
SELECT
  flight_id,
  ROUND(AVG(CASE WHEN my_blended_from_deg IS NOT NULL THEN 1.0 ELSE 0.0 END), 2) AS refined_share,
  ROUND(PMOD(DEGREES(ATAN2(AVG(SIN(RADIANS(my_blended_from_deg))), AVG(COS(RADIANS(my_blended_from_deg))))), 360), 0)
    AS my_blended_from_deg
FROM derived
GROUP BY flight_id
ORDER BY refined_share DESC
```

On the gustiest flight the derived wind comes from about 23° (north-north-east). That is between the
controller's N and NE sectors, where the controller cannot say it.

---

## Step 5: compare with the shipped column

`blended_wind_reference` is not in the Genie space, so run this step in the SQL editor: the steps 1 to 4 query
(the complete query below) joined to `blended_wind_reference` on `flight_id` and `t_s`.

The agreement metric, over motors-on samples:
- **source agreement**: the share of samples where both yours and the shipped column agree on *whether* the
  direction is tilt-refined (`blended_wind_source = 'blended'`);
- **direction difference**: where both are refined, the absolute angle between `my_blended_from_deg` and
  `blended_wind_from_deg`, wrapped. Report its median, its 99th percentile and the share within 1°;
- **for contrast**: the same angle between the controller's sector and the shipped direction.

> **Prompt 5.** *Compare my_blended_from_deg with blended_wind_from_deg. Report the share of samples where both
> agree on whether the direction is refined (blended_wind_source = 'blended'). Where both are refined, report the
> median and 99th-percentile absolute wrapped difference in degrees and the share within 1°. Also report the median
> absolute difference between fc_wind_from_deg and blended_wind_from_deg.*

<!-- check -->
```sql
SELECT
  COUNT(*) AS samples,
  ROUND(AVG(CASE WHEN (my_blended_from_deg IS NOT NULL) = (blended_wind_source = 'blended') THEN 1.0 ELSE 0.0 END), 4)
    AS source_agreement,
  COUNT_IF(both_refined) AS both_refined,
  ROUND(PERCENTILE(CASE WHEN both_refined THEN diff_deg END, 0.5), 3) AS median_diff_deg,
  ROUND(PERCENTILE(CASE WHEN both_refined THEN diff_deg END, 0.99), 3) AS p99_diff_deg,
  ROUND(AVG(CASE WHEN both_refined THEN CASE WHEN diff_deg <= 1 THEN 1.0 ELSE 0.0 END END), 4) AS within_1deg,
  ROUND(PERCENTILE(CASE WHEN both_refined THEN fc_diff_deg END, 0.5), 1) AS fc_sector_median_diff_deg
FROM (
  SELECT
    *,
    my_blended_from_deg IS NOT NULL AND blended_wind_source = 'blended' AS both_refined,
    ABS(PMOD(my_blended_from_deg - blended_wind_from_deg + 180, 360) - 180) AS diff_deg,
    ABS(PMOD(fc_wind_from_deg - blended_wind_from_deg + 180, 360) - 180) AS fc_diff_deg
  FROM derived
  JOIN blended_wind_reference USING (flight_id, t_s)
) d
```

**Result on release 0** (open-source Spark 4.0.1; a Databricks SQL warehouse gives the same except a 0.13° 99th
percentile and 99.73 % within 1°):

| Metric | Value |
|---|---|
| motors-on samples | 33,838 |
| source agreement | 99.99 % |
| both refined | 29,673 |
| median difference | 0.02° |
| 99th percentile difference | 0.19° |
| within 1° | 99.66 % |
| controller sector vs shipped, median | 13.8° |

What the numbers mean:
- The derived column reproduces the shipped one to a few hundredths of a degree on almost every sample.
- The 45° sectors sit 13.8° from it.
- The few larger differences come at moments when a sample sits right at a threshold, such as a steady test or
  the 5 s freshness limit. There a small timing difference decides which side it falls on.
- On flights where the blended wind was recorded live (`flights.has_live_blended_wind`), the reference computed it
  from the raw sample stream. Here it is computed from the published rows.

---

## The complete query

All five steps in one statement. Run it in the SQL editor: its last step reads `blended_wind_reference`, which the
Genie space does not include.

<!-- full -->
```sql
WITH
samples AS (
  SELECT
    flight_id, t_s, vel_north_mps AS vn, vel_east_mps AS ve, heading_deg, pitch_deg, roll_deg,
    fc_wind_speed_mps, fc_wind_from_deg,
    ROW_NUMBER() OVER (PARTITION BY flight_id ORDER BY t_s) AS n
  FROM telemetry
  WHERE motors_on
    AND fc_wind_speed_mps IS NOT NULL
    AND vel_north_mps IS NOT NULL AND vel_east_mps IS NOT NULL AND vel_down_mps IS NOT NULL
    AND heading_deg IS NOT NULL AND pitch_deg IS NOT NULL AND roll_deg IS NOT NULL
),
spans AS (
  SELECT
    s.*,
    LAG(t_s, 8) OVER w AS t_a, LAG(vn, 8) OVER w AS vn_a, LAG(ve, 8) OVER w AS ve_a,
    LAG(heading_deg, 8) OVER w AS h_a,
    LAG(t_s, 4) OVER w AS t_m, LAG(vn, 4) OVER w AS vn_m, LAG(ve, 4) OVER w AS ve_m,
    LAG(heading_deg, 4) OVER w AS h_m, LAG(pitch_deg, 4) OVER w AS pitch_m, LAG(roll_deg, 4) OVER w AS roll_m
  FROM samples s
  WINDOW w AS (PARTITION BY flight_id ORDER BY n)
),
spans_ok AS (
  SELECT
    *,
    (vn - vn_a) / (t_s - t_a) AS acc_n,
    (ve - ve_a) / (t_s - t_a) AS acc_e,
    (PMOD(heading_deg - h_a + 180, 360) - 180) / (t_s - t_a) AS yaw_rate_dps
  FROM spans
  WHERE t_a IS NOT NULL AND t_s - t_a >= 0.5 AND t_s - t_a < 1.2
),
steady AS (
  SELECT * FROM spans_ok WHERE HYPOT(acc_n, acc_e) <= 1.0 AND ABS(yaw_rate_dps) <= 30
),
tilt AS (
  SELECT
    flight_id, n, t_m, fc_wind_speed_mps,
    vn_m - (COS(RADIANS(h_m)) * air.x - SIN(RADIANS(h_m)) * air.y) AS tilt_n,
    ve_m - (SIN(RADIANS(h_m)) * air.x + COS(RADIANS(h_m)) * air.y) AS tilt_e
  FROM (
    SELECT
      *,
      AGGREGATE(
        SEQUENCE(1, 12),
        NAMED_STRUCT('x', CAST(0 AS DOUBLE), 'y', CAST(0 AS DOUBLE)),
        (a, i) -> NAMED_STRUCT(
          'x', y_fwd / (0.35408 + 0.02293 * HYPOT(a.x, a.y)),
          'y', y_right / (0.49623 + 0.01954 * HYPOT(a.x, a.y)))) AS air
    FROM (
      SELECT
        *,
        -9.81 * TAN(RADIANS(pitch_m)) - (-0.13491)
          - (COS(RADIANS(h_m)) * acc_n + SIN(RADIANS(h_m)) * acc_e) AS y_fwd,
        9.81 * TAN(RADIANS(roll_m)) / COS(RADIANS(pitch_m)) - 0.00804
          - (-SIN(RADIANS(h_m)) * acc_n + COS(RADIANS(h_m)) * acc_e) AS y_right
      FROM steady
    ) balance
  ) inverted
),
smooth_k AS (
  SELECT
    *,
    CASE WHEN LAG(t_m) OVER w IS NULL OR t_m - LAG(t_m) OVER w >= 3 THEN 1 ELSE 0 END AS restart,
    LEAST((t_m - LAG(t_m) OVER w) / 3.0, 1.0) AS k
  FROM tilt
  WINDOW w AS (PARTITION BY flight_id ORDER BY n)
),
smooth_seg AS (
  SELECT
    *,
    SUM(restart) OVER (PARTITION BY flight_id ORDER BY n ROWS UNBOUNDED PRECEDING) AS segment,
    CASE WHEN restart = 1 THEN 1.0 ELSE k END AS weight,
    CASE WHEN restart = 1 THEN 0.0 ELSE LN(1 - k) END AS log_keep
  FROM smooth_k
),
smooth AS (
  SELECT
    flight_id, n, t_m,
    EXP(log_keep_sum) * SUM(weight * EXP(-log_keep_sum) * tilt_n) OVER seg AS lp_n,
    EXP(log_keep_sum) * SUM(weight * EXP(-log_keep_sum) * tilt_e) OVER seg AS lp_e
  FROM (
    SELECT *, SUM(log_keep) OVER seg AS log_keep_sum
    FROM smooth_seg
    WINDOW seg AS (PARTITION BY flight_id, segment ORDER BY n ROWS UNBOUNDED PRECEDING)
  ) c
  WINDOW seg AS (PARTITION BY flight_id, segment ORDER BY n ROWS UNBOUNDED PRECEDING)
),
latest AS (
  SELECT
    s.*,
    LAST_VALUE(m.t_m, TRUE) OVER w AS tilt_t,
    LAST_VALUE(m.lp_n, TRUE) OVER w AS tilt_n,
    LAST_VALUE(m.lp_e, TRUE) OVER w AS tilt_e
  FROM samples s
  LEFT JOIN smooth m ON m.flight_id = s.flight_id AND m.n = s.n
  WINDOW w AS (PARTITION BY s.flight_id ORDER BY s.n ROWS UNBOUNDED PRECEDING)
),
derived AS (
  SELECT
    *,
    CASE
      WHEN tilt_t IS NOT NULL AND t_s - tilt_t < 5 AND HYPOT(tilt_n, tilt_e) >= 0.3
           AND fc_wind_speed_mps > 0 AND fc_wind_from_deg IS NOT NULL
      THEN PMOD(fc_wind_from_deg + GREATEST(-22.5, LEAST(22.5,
             PMOD(DEGREES(ATAN2(-tilt_e, -tilt_n)) - fc_wind_from_deg + 180, 360) - 180)), 360)
    END AS my_blended_from_deg
  FROM latest
)
SELECT
  COUNT(*) AS samples,
  ROUND(AVG(CASE WHEN (my_blended_from_deg IS NOT NULL) = (blended_wind_source = 'blended') THEN 1.0 ELSE 0.0 END), 4)
    AS source_agreement,
  COUNT_IF(both_refined) AS both_refined,
  ROUND(PERCENTILE(CASE WHEN both_refined THEN diff_deg END, 0.5), 3) AS median_diff_deg,
  ROUND(PERCENTILE(CASE WHEN both_refined THEN diff_deg END, 0.99), 3) AS p99_diff_deg,
  ROUND(AVG(CASE WHEN both_refined THEN CASE WHEN diff_deg <= 1 THEN 1.0 ELSE 0.0 END END), 4) AS within_1deg,
  ROUND(PERCENTILE(CASE WHEN both_refined THEN fc_diff_deg END, 0.5), 1) AS fc_sector_median_diff_deg
FROM (
  SELECT
    *,
    my_blended_from_deg IS NOT NULL AND blended_wind_source = 'blended' AS both_refined,
    ABS(PMOD(my_blended_from_deg - blended_wind_from_deg + 180, 360) - 180) AS diff_deg,
    ABS(PMOD(fc_wind_from_deg - blended_wind_from_deg + 180, 360) - 180) AS fc_diff_deg
  FROM derived
  JOIN blended_wind_reference USING (flight_id, t_s)
) d
```

## Notes

- The SQL uses Databricks SQL functions that also exist in Apache Spark: `PMOD`, `HYPOT`, `AGGREGATE`,
  `SEQUENCE`, `NAMED_STRUCT`, `LAST_VALUE(x, TRUE)`, `PERCENTILE` and `COUNT_IF`.
- "Gustiest" needs only the controller's wind *speed*, not this derivation. The derivation is about *direction*:
  what the tilt adds where the controller says only "N" or "NE".
- Licence: this guide and its SQL are covered by the repository's [LICENSE](../../../LICENSE.txt). The data is
  CC-BY-4.0 (see [`../data/README.md`](../data/README.md)).
