# Wind and dock-landing flights of a small quadcopter: release 0

Thirteen real outdoor flights of **a sub-250 g consumer quadcopter**, as three tables and a reference table:

- **7 wind flights**: light to moderate wind, at three sites. Four are operator flights flown mostly through automated
  manoeuvres (dashes, lines, orbits, helices, figure-eights, slaloms). Three are system-identification flights with programmed stick
  excitation.
- **6 autonomous landing attempts on a charging dock**: spiral approach, low hold, commit, touchdown. Each has the
  dock's own verdict on whether the aircraft seated on its charging contacts.

The flight controller is a closed, commercial one. You command sticks, not motors. Its own wind estimate comes with
the flight. A finer "blended" wind direction, worked out from the same telemetry, is kept apart in a reference table
(see below), so that you can derive your own from the raw columns and compare.

| File | Rows | What |
|---|---|---|
| `flights.parquet` | 13 | one row per flight |
| `telemetry.parquet` | 33,851 | one row per flight-controller sample, about 10 Hz |
| `landings.parquet` | 6 | one row per dock landing attempt |
| `blended_wind_reference.parquet` | 33,851 | the blended wind for each telemetry sample (reference answer) |

The files are parquet, zstd-compressed.

**Licence.** [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).

## What was removed (anonymisation)

- **Positions.** There are no satellite-navigation coordinates. Positions are in a local frame whose origin is the
  take-off point of each flight.
- **Time.** There is no wall-clock time. `t_s` counts seconds from each flight's first sample. Days are numbered
  (`day_1`, `day_2`, `day_3`, in date order) and so are sites (`site_1`, ...). Neither carries a calendar date or a
  place.
- **Ids.** Flight and landing ids are keyed hashes. The key and the map back to the source stay private.
- **Other data.** There is no video, no audio, no raw radio-link bytes, no device identifiers and no free text.
- **Names.** Vendor, product and internal software names are removed. Where a value came from the flight controller,
  the column says so (`fc_...`).

Wind direction and compass heading are left north-referenced, because the wind science needs them.

## Frames, signs and units

- **Local frame:** x north, y east, z up, in metres. The origin is the take-off point: the position estimate at the
  flight's first sample, so every flight starts at (0, 0, 0). For the dock flights the take-off point is the dock seat.
- **Angles:** degrees.
  - Heading and yaw are compass bearings, clockwise from north, in [0, 360).
  - Pitch is nose-up positive, so forward flight is negative. Roll is right-side-down positive. Both are the airframe's
    tilt, not the camera's.
- **Wind direction** is where the wind blows **from**, clockwise from north (meteorological convention).
- **Velocities** are over the ground in m/s. `vel_down_mps` is positive descending.
- **Sticks** are the commanded stick positions, from -1 to 1:
  - roll: + right;
  - pitch: + forward;
  - yaw: + clockwise;
  - throttle: + up.

## flights

| Column | Type | Meaning |
|---|---|---|
| `flight_id` | string | keyed hash, 16 hex characters |
| `site` | string | `site_1`, `site_2`, ...: take-off points within 150 m of each other are one site, numbered in order of first use |
| `session` | string | `day_1`, `day_2`, ...: the flight's day, numbered in date order |
| `kind` | string | `manual`: flown by the operator on the sticks. `automated_manoeuvres`: flown by the operator, mostly through automated manoeuvres the operator triggers (dashes, lines, orbits, helices, figure-eights, slaloms), each flown by a model-predictive controller. `system_identification`: programmed stick excitation (multisines, held pulses, speed sweeps, brake holds, slow ramps). `autonomous_dock_cycle`: an unattended take-off from the dock, spiral approach and landing. |
| `duration_s` | float | motors on to motors off, s |
| `airborne_s` | float | time with motors on and at least 0.3 m above the take-off point, s |
| `samples` | int | rows in `telemetry` |
| `has_live_blended_wind` | bool | true: the blended wind in `blended_wind_reference` was computed live in flight and recorded. false: it was computed afterwards by the same reference implementation from the same inputs (see *Blended wind*). |
| `ends_in` | string | `dock_landing`: the flight ended with a dock landing attempt (its outcome is in `landings`). `hand_catch`: the motors stopped more than 0.8 m above the take-off point with the range sensor at 0.2 m or less in the last 3 s (a hand under the aircraft). `ground_landing`: the motors stopped within 0.3 m of the take-off height. `unknown`: none of these. One flight is `unknown`: its motors stopped at 0.8 m with the range sensor reading 0, probably a low hand catch, just outside the rule. |

## telemetry

**Sampling.**
- There is one row per flight-controller sample. The rate is nominally 10 Hz: the median step is 0.100 s, ranging from
  0.05 to 0.22 s. The rows are not resampled, so `t_s` keeps the real sample times, to the millisecond.
- Faster or slower streams are joined to each row nearest-in-time, within a tolerance:
  - position and yaw: 50 Hz, within 0.05 s;
  - commanded sticks: within 0.1 s;
  - battery: about 1.6 Hz, within 1 s.
- A value with nothing within its tolerance is null.

| Column | Unit | Meaning |
|---|---|---|
| `flight_id` | | joins `flights` |
| `t_s` | s | time since the flight's first sample |
| `motors_on` | bool | the motors are spinning |
| `flight_phase` | | `taking_off`: from motor start until the first climb stops (at 0.3 m or more above take-off, no longer climbing). `landing`: the final descent or touchdown (or catch), up to motor stop. `in_air`: everything between. `on_ground`: motors off. Derived from motors, height and vertical speed, the same way for every flight. |
| `pos_x_m`, `pos_y_m`, `pos_z_m` | m | the flight controller's estimated position, relative to take-off (x north, y east, z up). z comes from barometric altitude minus its value at take-off. |
| `yaw_deg` | deg | the yaw of the same pose estimate, as a compass bearing |
| `height_above_surface_m` | m | the downward range sensor, in 0.1 m steps. Null when the aircraft is more than 5 m above the take-off point: beyond that the sensor loses the ground and holds stale values. It reads 0 to 0.2 m on the ground, and drops to about 0.2 m when a hand is under the aircraft. |
| `vel_north_mps`, `vel_east_mps`, `vel_down_mps` | m/s | ground velocity from the flight controller's navigation estimate |
| `pitch_deg`, `roll_deg` | deg | the airframe's tilt |
| `heading_deg` | deg | compass heading of the nose |
| `fc_wind_speed_mps` | m/s | the flight controller's own wind estimate, in 0.1 m/s steps. It is 0 on the ground. |
| `fc_wind_from_deg` | deg | its direction, in 45° sectors only (0, 45, ..., 315). Null when its speed is 0. |
| `battery_pct` | % | charge remaining |
| `battery_v` | V | pack voltage |
| `battery_a` | A | pack current, **negative while discharging** |
| `stick_roll`, `stick_pitch`, `stick_yaw`, `stick_throttle` | -1..1 | What the aircraft was commanded. This is the ground station's stick frames while it was flying. In between, it is the handheld controller's own sticks, which were centred throughout this release. The first rows of the take-offs from the ground show the motor-start stick pattern; the dock take-offs were commanded without it. |

## landings

One row per landing attempt on the dock: the 6 `autonomous_dock_cycle` flights, one attempt each.

**What happens in an attempt.**
1. The aircraft takes off from the dock.
2. It flies a spiral course: 1.5 laps out to a 1 m radius and 1.5 laps back in, descending.
3. It holds about 0.45 m above the dock seat (the *low hold*). It waits for its position error to the seat, averaged
   over 0.5 s, to fall inside a gate: about 1.5 cm, 3°, and under about 1 cm/s.
4. It **commits**: roll and pitch are centred and the throttle goes fully down until the motors stop.

Whether it **seated** comes from the dock's contacts. A seated aircraft makes the dock's charging contacts read the
aircraft's battery, about 30 samples in the seconds after touchdown. A miss gives 0. The landing controller's own
verdict agrees with the contacts on all six.

| Column | Unit | Meaning |
|---|---|---|
| `landing_id` | | keyed hash |
| `flight_id` | | joins `flights` |
| `t_commit_s` | s | the commit, on the flight's `t_s` clock |
| `outcome` | | `seated` or `not_seated` |
| `approach` | | `spiral`: the course flown before the low hold |
| `commit_error_cm` | cm | horizontal error to the dock seat at the commit, averaged over the gate window |
| `commit_heading_error_deg` | deg | heading error to the seat at the commit |
| `commit_speed_cmps` | cm/s | speed over the gate window |
| `low_hold_s` | s | time spent in the low hold before the commit |
| `retries` | | climbs back for another descent when the gate was not met within 20 s |
| `contact_samples` | | the dock's battery samples after touchdown (about 30 seated, 0 not) |

## blended_wind_reference

A reference answer, kept out of `telemetry` on purpose: the raw table has only the flight controller's wind, and the
blended direction below is one way to refine it. One row per telemetry sample, joined on (`flight_id`, `t_s`). Every
telemetry sample has one here (33,851 rows).

| Column | Unit | Meaning |
|---|---|---|
| `flight_id`, `t_s` | | the telemetry sample |
| `blended_wind_speed_mps` | m/s | the blended wind's speed: the flight controller's |
| `blended_wind_from_deg` | deg | the blended wind's direction: the sector refined by body tilt (below). Null when the speed is 0. |
| `blended_wind_source` | | `blended`: the direction was refined by the tilt. `fc`: the tilt had nothing steady to say, so the direction is the flight controller's sector. |
| `blended_wind_quality` | 0-1 | the share of the last 5 s of samples steady enough to read the wind from the tilt |

## Blended wind

The flight controller reports wind speed well, but gives the direction only as one of eight 45° sectors. In a wind
near a sector boundary it flips between two sectors many times a minute. The blended wind keeps the controller's
**speed** and refines its **direction** from the physics of a hovering multirotor:

1. **Steady flight only.** A sample counts as steady when the ground acceleration over the last 0.8 s is under
   1 m/s² and the yaw rate is under 30°/s.
2. **Tilt gives the air-relative velocity.** In steady flight the airframe tilts into the relative wind, so that
   thrust balances drag.
   - In body axes, the tilt-implied acceleration is g·tan(pitch) and g·tan(roll)/cos(pitch), less a small fixed bias
     and the measured acceleration.
   - It equals a drag law, (c1 + c2·|v_air|)·v_air, with separate coefficients for the forward and lateral axes. This
     is solved for the air-relative velocity v_air by fixed-point iteration.
3. **Wind from the velocity triangle.** v_air is rotated to north/east by the heading. Wind = ground velocity − air
   velocity. It is smoothed over about 3 s, and is stale after 5 s without a steady sample.
4. **Kept inside the sector.** The blended direction is the tilt wind's direction clamped to within ±22.5° of the
   controller's sector centre. The sector stays the authority and the tilt only places the wind within it.
   - The blend is used when the tilt wind is fresh and at least 0.3 m/s.
   - Otherwise the source is `fc`.
   - On the ground it is always `fc`.

**Where it comes from in this release.**
- The 7 flights with `has_live_blended_wind = true` carry the values computed live in flight.
- For the other 6, the same reference implementation was run afterwards over the same flight-controller samples.
- On the 7 live flights, the reference implementation's `blended_wind_source` agrees with the live one on 100.0 % of
  samples.

The blended wind is an *estimate from the aircraft's own sensors*, not an anemometer reading. Near the ground (the dock
flights hover at 0.45 to 1.2 m) the controller's wind is mostly noise, in speed and direction.

## Gust metric

**gust excess** (m/s) = (the highest 3 s running mean of `fc_wind_speed_mps`) − (the flight's mean `fc_wind_speed_mps`).

- **Samples:** `motors_on` and `pos_z_m` ≥ 1 m, without the first 5 s after first reaching 1 m and the last 5 s before
  the motors stop. Trimming the end matters: a hand catch makes the wind estimate jump as the hand takes the weight.
- **Bins:** average into 1 s bins of `floor(t_s)`. Each bin needs at least 5 samples. The flight mean is the mean of
  these bins.
- **Running mean:** the 3 s running mean spans 3 consecutive 1 s bins.
- **Minimum data:** only flights with at least 60 such bins get a value; the others have none. Here that is the 7 wind
  flights, not the dock flights.

The *gustiest* flight has the largest gust excess. Report its peak (the 3 s gust) and mean beside it.

Why 3 s and in m/s:
- 3 s is the standard gust averaging time.
- It averages about 7 independent updates of the controller's 0.1 m/s-step estimate.
- An excess in m/s does not reward calm flights the way a peak/mean ratio does.

Beware of `max − mean` over raw samples: a single catch spike can win it.

Before release, an automated gate recomputed this metric from `telemetry` and checked three results:
- the gustiest flight;
- the calmest flight by mean wind;
- the dock outcomes: 4 of 6 seated.

## Known limits

- **Wind:** the controller's wind estimate is band-limited to seconds-scale changes. It is not meteorological
  turbulence.
- **Position:** it is the flight controller's navigation estimate, not ground truth. It can drift slowly by a metre or
  two over a flight.
- **Yaw columns:** `yaw_deg` (pose) and `heading_deg` (compass) differ by a median of 0.1° and at most 7°. Both are
  kept as the contract asks.
- **Height above surface:** null above 5 m, and stale readings below that are possible.
- **Flight endings:** `ends_in` comes from simple rules on the last seconds of the flight; one flight is `unknown`.
- **Sampling:** the rows follow the flight controller's own sampling, not an exact 10 Hz grid (see *Sampling*).

## How it was made

The tables were exported from the aircraft's recorded telemetry by a private pipeline, which also holds the hash key.
An automated release gate checked them before publication. It failed on anything identifying or off the published
contract, and recomputed the answers above.
