# Casino Floor Simulation Demo Scope

This document scopes a future demo of a simplified casino floor. It is a research-backed product and data design artifact, not an implementation plan for real-money gambling software.

The target experience is a visually approachable, 8-bit-style simulation where synthetic patrons move around a small casino floor, use slot machines, visit a bar, and generate realistic slot telemetry. The user does not play or control any games. They observe, configure, start, pause, and inspect an agent-based simulation. The simulation state should live in a Databricks App backed by Lakebase, with downstream Databricks tables and Genie analysis added after the live simulation model is credible.

## Current Direction

Key product choices:

- Build a richer React-style Databricks App with AppKit, not Streamlit.
- Use Lakebase as the application database for simulation state: floor layout, machine state, patron state, balances, activity state, scenario configuration, and authoritative event records.
- Keep the first phase focused on the live agent-based simulation, not on generating a synthetic historical day for analytics.
- Use a hybrid model: ABM-style patron movement and decisions, with discrete slot, jackpot, fault, meter, and configuration events.
- Keep the regulatory feel jurisdiction-neutral with light Las Vegas/Nevada flavor in terminology and controls.
- Treat Knowledge Assistant, Supervisor Agent, Genie, and simplified machine manuals as later layers once the simulation and emitted data are solid.
- Start anonymous, but design patron state so synthetic loyalty tiers can be added later.

## Demo Story

The demo should show how a casino operator could reason about a live slot floor from structured event and meter data. The front end makes the system tangible: patrons walk between machines, balances change, jackpots hit, machines fault, and the bar provides a non-gaming activity that changes foot traffic. The data layer makes the story credible: every visible interaction emits accounting-style records that resemble the concepts used by slot management, monitoring, and regulatory systems.

There should be no player-facing gambling interface. The user is a simulation observer/operator, not a patron. They can tune simulation parameters, inspect machine cards, view patron movement, and review telemetry, but they cannot click a slot machine, place a bet, or influence an outcome as a player.

The point is not to recreate a real slot system. The point is to preserve the shape of the real problem:

- Slot outcomes are stochastic, so short-term performance can look wrong even when a machine is operating normally.
- Operators compare actual win/hold to theoretical hold/PAR over enough coin-in to separate noise from a signal.
- Meters, tickets, jackpots, hand pays, status events, and configuration changes matter as much as individual spins.
- A conversational analytics layer is useful when it can explain whether an apparent anomaly is revenue mix, variance, maintenance, jackpot timing, or a data-quality issue.

## Domain Glossary

| Term | Demo meaning | Real-world anchor |
| --- | --- | --- |
| Coin-in | Total credits wagered on slot play, stored in cents. | Common slot accounting meter; AGCO aliases this to total bet, and US MICS definitions describe coin-in as total wagered. |
| Coin-out | Credits won and paid back by the terminal, stored in cents. | Metered wins paid by the terminal; large hand pays and progressives may be tracked separately depending on jurisdiction/system. |
| Handle | Business term for total amount wagered. | For slots, this generally maps to coin-in. |
| Drop | Cash or instruments accepted/removed through the machine or count process. | Real systems distinguish physical drop, bill-in, voucher-in, and related cash handling. |
| Actual win | Coin-in minus coin-out and other payout adjustments for an interval. | Used to compute actual hold. |
| Actual hold | Actual win divided by coin-in for a machine, bank, or floor segment. | A core operator metric; meaningful only over enough volume. |
| Theoretical hold / PAR | Expected house edge configured for the game/paytable. | Based on approved game math, paytable, denomination, and progressive rules. |
| RTP | Return to player; the inverse framing of theoretical hold. | A 92.5% RTP implies roughly 7.5% theoretical hold before demo simplifications. |
| Jackpot | A large win event, optionally including progressive awards and hand pays. | Real systems often separate terminal-paid wins, progressive awards, and attendant-paid jackpots. |
| Progressive contribution | Share of each eligible wager that increments a progressive jackpot meter. | Controlled by approved progressive rules and accounting. |
| TITO | Ticket-in, ticket-out voucher flow. | Cashless wagering instrument flow: voucher accepted, voucher printed, redeemed later. |
| Meter poll | Periodic snapshot of absolute machine counters. | Online slot monitoring systems reconcile machine meters to central systems. |
| OSMS | Online slot metering system. | Back-office system for machine meter collection and reconciliation. |
| SAS / G2S | Slot-machine-to-system communication idioms. | SAS is a long-running slot accounting protocol; G2S is an IGSA XML-based game-to-system standard. The demo should borrow concepts, not implement either protocol. |
| Player session | A contiguous visit to a machine by a patron, anonymous by default. | Real systems may use player cards; the demo should avoid personal data by default. |
| Hand pay | Attendant-paid jackpot or payout. | Important for separating large manual payouts from ordinary machine-paid coin-out. |

Useful source anchors for later write-up and in-app footnotes:

- AGCO meter definitions: <https://www.agco.ca/en/lottery-and-gaming/responsibilities-and-resources/guides/8-meters>
- US tribal MICS definitions: <https://www.ecfr.gov/current/title-25/subtitle-A/chapter-I/subchapter-H/part-542/subpart-A/section-542.2>
- Nevada slot audit FAQs and OSMS references: <https://www.gaming.nv.gov/divisions/audit-division/faqs/slots/>
- IGSA G2S overview: <https://igsa.org/committees/g2s-game-to-system-committee/>
- GLI standards catalog: <https://gaminglabs.com/gli-standards>

## Simulation Model

The agent-based modeling approach is viable at the intended scale. With 20 machines and roughly 50-100 patrons, the core loop is small: each tick updates patron intent, movement, and resource assignment, while slot usage, jackpots, faults, and meter polls are discrete events. CPU is unlikely to be the limiting factor; the main risk is over-writing high-frequency movement state to Lakebase or over-streaming position updates to the client.

See `ABM_RESEARCH.md` for the technology comparison and recommendation. The current recommendation is Mesa-first event generation with an AppKit replay UI. Mesa produces events, meter snapshots, and sampled patron positions; the Databricks App replays and inspects generated runs.

Recommended framing:

- Use ABM-style rules for patron movement, motivation, patience, and activity choice.
- Use discrete events for money movement, slot outcomes, jackpots, machine faults, meter polls, and configuration changes.
- Treat the event log as the authoritative business truth.
- Keep per-frame animation details transient in the React client or server process unless sampled state is needed for multi-client viewing.

Implementation options:

- A TypeScript simulator inside the AppKit server is the simplest fit for the first live version because it can update Lakebase through the same tRPC/server layer that drives the UI.
- A Python simulator, potentially using Mesa-style ABM patterns, may be useful later for accelerated historical runs or model experimentation.
- A pure discrete-event simulator is efficient for telemetry generation, but it is less natural for showing patrons moving through the floor. A hybrid ABM/DES model is the best fit.

Research anchors:

- Casino-floor simulation and slot mix research from UNLV suggests Monte Carlo and transition-probability approaches are already used for slot-floor questions.
- Mesa-style ABM examples show that grid movement, agent state, and scheduled actions are mature patterns, even if the first implementation does not use Mesa directly.
- At the proposed scale, the constraint is database/write frequency and UI synchronization, not simulation CPU.

### Floor

Start with a small grid-based floor:

- 20 slot machines arranged in 4 banks of 5 machines.
- 1 bar or lounge area.
- 1 entrance/exit.
- Optional service corridor or technician spawn point.

Each slot has:

- `machine_id`, `bank_id`, `zone`, and grid position.
- `theme`, `denomination_cents`, `paytable_id`, and `theoretical_hold_pct`.
- A volatility class: `LOW`, `MEDIUM`, or `HIGH`.
- A status: `IN_SERVICE`, `OUT_OF_SERVICE`, `SOFT_FAULT`, `DOOR_OPEN`, or `BILL_VALIDATOR_FAULT`.
- Optional progressive participation.

### Patrons

Patrons are synthetic agents with enough individuality to create believable flow without introducing privacy issues.

Recommended patron attributes:

- `patron_id`: synthetic and non-identifying.
- `budget_cents`: maximum amount they are willing to spend.
- `wallet_cents`: current available balance.
- `risk_preference`: preference for low, medium, or high volatility machines.
- `denomination_preference`: preferred bet size.
- `patience`: how long they wait before moving.
- `bar_affinity`: probability of taking a break at the bar.
- `session_goal`: entertainment time, jackpot seeking, or budget-constrained play.

Patron states:

- `ENTERING`
- `WALKING`
- `PLAYING_SLOT`
- `AT_BAR`
- `WAITING`
- `EXITING`

Future patron attributes can include synthetic loyalty tier, visit frequency, preferred bank, or comp/free-play eligibility. The initial schema should leave room for those fields without making loyalty modeling part of the first build.

### Machine Outcome Simplification

Do not model full reel math. Use fixed synthetic outcome distributions per game class:

- Low volatility: frequent small wins, tight actual hold around theoretical hold.
- Medium volatility: occasional medium wins, more visible short-term variance.
- High volatility: fewer wins, rare large payouts, widest short-term variance.
- Progressive bank: small contribution from eligible wagers, rare jackpot hit.

Each spin settles into:

- `bet_cents`
- `win_cents`
- optional `jackpot_cents`
- optional `progressive_contribution_cents`

This is enough to support operator analytics without pretending to be certified game math.

### Live State Versus Persisted State

Lakebase should store durable app state and business events:

- `simulation_runs`: seed, scenario, speed, status, start/end timestamps.
- `floor_entities`: slots, bar, entrance, exit, walls, zones, and coordinates.
- `machine_config`: denomination, volatility, paytable, theoretical hold, progressive eligibility.
- `machine_state`: current status, current meters, active session, fault state, progressive meter.
- `patron_state`: synthetic patron attributes, current location, target, wallet, budget, current activity, optional future loyalty tier.
- `activity_events`: append-only business events emitted by the simulator.
- `meter_polls`: periodic absolute meter snapshots.
- `scenario_config`: toggles for faults, jackpot behavior, arrival rate, bar attractiveness, and anomaly injection.

Transient state should remain outside the database unless sampled:

- Pixel-level position interpolation.
- Animation phase and sprite state.
- In-progress pathfinding waypoints.
- Short-lived UI hover/selection state.
- High-frequency per-frame diffs.

### Configurable Parameters

The later app should expose a small control panel:

- Number of active patrons.
- Simulation speed.
- Floor traffic intensity.
- Jackpot frequency multiplier.
- Machine fault frequency.
- Bar attractiveness.
- Random seed.
- Optional anomaly scenario toggle.

Suggested defaults:

- 20 machines.
- 50-100 patrons over a 5-15 minute accelerated window.
- One progressive bank.
- One flaky bill validator.
- One machine with deliberately thin coin-in that triggers a false positive.
- One paytable/configuration change during the simulated day.

## Telemetry Design

The data model should look like a simplified slot monitoring feed. The most important design choice is to represent both event deltas and periodic absolute meter snapshots.

### Event Types

Use a small controlled set:

- `SESSION_START`
- `SESSION_END`
- `BET_SETTLED`
- `CASH_IN`
- `TICKET_OUT`
- `JACKPOT_HANDPAY`
- `MACHINE_STATUS`
- `METER_POLL`
- `CONFIG_CHANGE`
- `BAR_VISIT`

`BAR_VISIT` is not part of slot accounting, but it helps explain occupancy, dwell time, and player movement.

### Core Event Schema

```json
{
  "event_id": "uuid",
  "event_ts": "2026-05-13T15:42:01.123Z",
  "event_type": "BET_SETTLED",
  "simulation_run_id": "run-2026-05-13-001",
  "source": "casino_floor_simulator_v1",
  "machine_id": "slot-014",
  "bank_id": "bank-c",
  "zone": "main-floor",
  "session_id": "session-uuid",
  "patron_id": "synthetic-uuid",
  "game_id": "video-poker-03",
  "theme": "Neon Buffalo",
  "paytable_id": "PAR-NEON-BUFFALO-925",
  "denomination_cents": 25,
  "bet_cents": 100,
  "win_cents": 0,
  "coin_in_delta_cents": 100,
  "coin_out_delta_cents": 0,
  "bill_in_delta_cents": 0,
  "voucher_in_delta_cents": 0,
  "voucher_out_delta_cents": 0,
  "jackpot_handpay_delta_cents": 0,
  "progressive_contribution_delta_cents": 1,
  "machine_status": "IN_SERVICE",
  "fault_code": null,
  "theoretical_hold_pct": 7.5
}
```

### Meter Snapshot Schema

`METER_POLL` events should capture absolute counters as of a poll time:

```json
{
  "event_id": "uuid",
  "event_ts": "2026-05-13T15:45:00.000Z",
  "event_type": "METER_POLL",
  "simulation_run_id": "run-2026-05-13-001",
  "machine_id": "slot-014",
  "meters": {
    "coin_in_cents": 412500,
    "coin_out_cents": 381250,
    "bill_in_cents": 120000,
    "voucher_in_cents": 220000,
    "voucher_out_cents": 90500,
    "jackpot_handpay_cents": 0,
    "games_played": 4125
  }
}
```

Absolute meters let the demo tell reconciliation stories. Event deltas let Genie answer session, patron-flow, and time-window questions.

## Databricks Table Model

Keep the medallion model simple enough for a demo while preserving realistic analytical surfaces. This is downstream of the live simulation work. The first app can maintain state and event records in Lakebase; later, an export or ingestion job can land the accounting-relevant events and meter polls into Delta tables for Genie.

### Bronze

`bronze_slot_events`

- Raw synthetic event log.
- One row per emitted event.
- Contains semi-structured payload for event-specific fields.
- Good for replay, debugging, and traceability.

### Silver

`silver_slot_spins`

- One row per `BET_SETTLED`.
- Normalized machine, game, session, bet, win, jackpot, and progressive contribution fields.
- Good for actual hold, volatility, and jackpot analysis.

`silver_meter_polls`

- One row per machine per meter poll.
- Absolute counters plus calculated deltas from the previous poll.
- Good for OSMS-style reconciliation.

`silver_machine_status`

- One row per status transition.
- Includes status duration and fault code where applicable.
- Good for maintenance and availability questions.

`silver_patron_sessions`

- One row per machine session.
- Includes start/end time, duration, total coin-in, total coin-out, net result, and whether the patron visited the bar before or after the session.
- Good for occupancy and behavior questions.

### Gold

`gold_machine_daily`

- Machine-day summary.
- Metrics: coin-in, coin-out, actual_win, actual_hold_pct, theoretical_win, theoretical_hold_pct, hold_variance_bps, jackpots, games_played, uptime_pct, fault_count.

`gold_bank_hourly`

- Bank-hour summary for floor management.
- Metrics: active_sessions, occupancy_pct, coin-in, actual_hold_pct, jackpot-adjusted_hold_pct, bar-adjacent traffic, fault minutes.

`gold_anomaly_candidates`

- Precomputed flags and context.
- Example flags: `LOW_COIN_IN_FALSE_POSITIVE`, `HOLD_DRIFT_AFTER_VOLUME`, `METER_RECONCILIATION_GAP`, `FAULT_RATE_SPIKE`, `JACKPOT_DISTORTED_HOLD`, `CONFIG_CHANGE_BASELINE_SHIFT`.

`gold_progressive_summary`

- Progressive bank state over time.
- Metrics: seed, contribution, current meter, hit count, hit amount, reset time, eligible coin-in.

## Genie Space

Genie is not part of the first simulation milestone. Once the Lakebase-backed simulator produces credible events and meter polls, Genie should primarily sit on the gold and silver Delta tables. The table comments and column descriptions should teach it the operational language:

- Actual hold is noisy at low coin-in.
- Jackpot-adjusted hold excludes jackpot hand pays from ordinary payout analysis.
- Theoretical win is coin-in multiplied by theoretical hold.
- Meter reconciliation compares event-derived deltas to meter-poll deltas.
- Machine status and fault duration explain availability and some revenue anomalies.

Recommended Genie starter questions:

1. Which five machines had the largest gap between actual hold and theoretical hold today?
2. Of those machines, which have enough coin-in for the gap to be meaningful?
3. Show actual hold versus theoretical hold by bank for the last simulated hour.
4. Which machine looks anomalous before jackpot adjustment but normal after excluding jackpot hand pays?
5. Did any machines have meter reconciliation gaps between event deltas and meter polls?
6. Which machines had the most fault minutes, and how much coin-in did they lose compared with nearby machines?
7. Did the flaky bill validator reduce play, or did patrons move to other machines in the same bank?
8. Which machines had a configuration or paytable change, and how did their baseline theoretical hold change?
9. How much of the floor's win came from high-volatility machines versus low-volatility machines?
10. Did bar visits increase session duration or coin-in for adjacent machines?
11. Which anomaly candidates are likely normal variance due to low sample size?
12. What changed in bank C after the progressive jackpot hit?

## Anomaly And Maintenance Narratives

The demo needs anomalies that are explainable, not just surprising. These should be toggled or seeded into the simulation.

### Normal Variance Misread As A Problem

A high-volatility machine has a short cold streak and appears to hold far above PAR. Genie should identify that coin-in is too low to conclude drift and recommend waiting for more volume or pooling by game type.

Signal:

- High `hold_variance_bps`.
- Low `coin_in_cents`.
- No fault, config, or meter issue.

### Jackpot-Adjusted Hold

A progressive jackpot hits in one bank and actual hold collapses for the period. Genie should separate ordinary coin-out from jackpot hand pay and show that ex-jackpot hold is within range.

Signal:

- Large `jackpot_handpay_delta_cents`.
- Low raw actual hold.
- Normal jackpot-adjusted hold.

### Bill Validator Fault

One machine intermittently rejects bills or vouchers. Patrons abandon it more quickly, session count drops, and nearby machines pick up traffic.

Signal:

- `BILL_VALIDATOR_FAULT` status events.
- Lower uptime.
- Shorter sessions.
- Lower bill-in and voucher-in.
- Nearby machines with increased occupancy.

### Meter Reconciliation Gap

Event-derived coin-in for a machine does not match the next meter poll delta. This should look like a data-quality or monitoring issue, not a game fairness issue.

Signal:

- Difference between summed event deltas and meter deltas.
- No corresponding jackpot or configuration change.
- Genie flags the machine for OSMS/feed investigation.

### Configuration Baseline Shift

A paytable changes during the day, moving theoretical hold from 7.5% to 8.2%. If analytics compare post-change performance to the old baseline, it looks like hold drift.

Signal:

- `CONFIG_CHANGE` event.
- New `paytable_id`.
- New theoretical hold.
- Apparent anomaly disappears when segmented by config window.

### Occupancy Mix Shift

The bar becomes attractive during a simulated event. Nearby banks get more casual, lower-denomination play, while a high-limit/high-volatility bank has fewer but larger sessions.

Signal:

- Increased `BAR_VISIT` events.
- Bank-level traffic mix shift.
- Different denomination and volatility mix.
- Floor hold changes without machine-level issues.

## Regulatory Realism

The demo should explicitly avoid claiming regulatory compliance. It should borrow the language and control concepts that make the data story recognizable.

Recommended UI copy:

> Educational simulation only. No real-money wagering, certified RNG, or regulatory approval is implied.

Recommended realism cues:

- A visible PAR card per machine with theoretical RTP/hold, denomination, volatility class, and paytable ID.
- A locked paytable/config panel to imply approved configuration control.
- A read-only event log showing spin settlement, meter polls, jackpot hand pays, and status events.
- A progressive rules panel with seed, contribution percentage, eligibility, and reset behavior.
- Synthetic patron identifiers only, with no real PII or account data.
- No UI affordance that lets the user place a bet, spin a slot, or otherwise act as a patron.

Source areas for the regulatory backdrop:

- GLI RNG and gaming-device standards: <https://gaminglabs.com/services/igaming/random-number-generator-rng/> and <https://gaminglabs.com/gli-standards>
- Nevada Regulation 14 and Technical Standard 3: <https://www.gaming.nv.gov/regulations/gaming-statutes-regulations/>
- UK Gambling Commission RTS 7 and RTS 9 for readable RNG/progressive language: <https://www.gamblingcommission.gov.uk/standards/remote-gambling-and-software-technical-standards/rts-7-generation-of-random-outcomes> and <https://www.gamblingcommission.gov.uk/standards/remote-gambling-and-software-technical-standards/rts-9-progressive-jackpot-systems>

## Suggested Future Architecture

The best fit for this repository is an AppKit + Lakebase Databricks App for the replay and inspection surface, paired with a Mesa-based generator for simulation runs, followed later by the programmatic Databricks setup pattern used by the existing agent demos.

- Use AppKit for a React UI with a PixiJS canvas floor, machine cards, replay controls, and telemetry panels.
- Use the Lakebase AppKit feature for replay state, generated runs, event records, sampled positions, and tRPC procedures.
- Avoid `config/queries/` and `useAnalyticsQuery` for Lakebase state; those are for warehouse analytics. Use server-side Lakebase queries via tRPC for simulator state.
- Add analytics/warehouse/Genie features later, after the simulator exports accounting events and meter polls to Delta.
- Use the programmatic setup pattern from `demos/bee-pollinator` later for Delta tables, Genie Space creation, optional Knowledge Assistant, and optional Supervisor Agent.
- See `VISUAL_DESIGN.md` for the frontend rendering and asset recommendation. The current recommendation is PixiJS + `@pixi/react` + Tiled-authored maps, with React/AppKit handling controls and inspectors.

AppKit/Lakebase scaffolding notes for a later build:

- AppKit is a TypeScript/React framework for Databricks Apps with plugin-based support for Lakebase, analytics, Genie, jobs, and model serving.
- The Lakebase plugin is intended for persistent read/write app state, while AppKit analytics queries are intended for read-only warehouse data.
- Start by running `databricks apps manifest` for the target workspace and derive exact plugin/resource keys from the manifest.
- A likely first scaffold is `databricks apps init --name casino-floor --features lakebase ... --run none`, with the Lakebase branch and database supplied from the manifest-required resource fields.
- If analytics is added later, scaffold or migrate toward combined `analytics,lakebase` support with the SQL warehouse supplied explicitly.
- Lakebase apps should be deployed before local development so the app service principal creates and owns its schema.
- The app name must stay within Databricks Apps naming limits: lowercase letters, numbers, hyphens, and no more than 26 characters.

Recommended future project shape:

```text
demos/casino-floor/
  README.md
  SCOPING.md
  app.yaml
  databricks.yml
  package.json
  server/
    server.ts
  client/
    src/
      App.tsx
      components/
        FloorReplay.tsx
  src/
    shared/
  simulation/
    casino_floor/
  scripts/
    generate_run.py
    export_events_to_delta.py
    create_genie_space.py
    verify_demo.py
  data/
    regulatory_notes/
```

### First Build Slice

If this moves from scoping to implementation, the smallest credible slice is:

1. Scaffold an AppKit + Lakebase app.
2. Define the Lakebase schema for generated runs, floor layout, machine config, replay samples, activity events, and meter polls.
3. Build the Mesa generator for patrons entering, walking, choosing activities, using machines, visiting the bar, and exiting.
4. Generate a short sample run and load it into Lakebase.
5. Render the casino floor as a PixiJS replay view with observer controls only.
6. Emit accounting-relevant slot events and meter polls from the same Mesa state transitions that drive the replay.
7. Seed three simulation scenarios: jackpot-adjusted hold, bill-validator fault, and low-volume false positive.

### Later Enhancements

- Add long-horizon generation, potentially up to a year or more of synthetic events, from the same Mesa rules.
- Export Lakebase events and meter polls to Delta and create bronze, silver, and gold tables.
- Add a Knowledge Assistant over a short curated regulatory/operator note set.
- Add a Supervisor Agent that routes structured questions to Genie and policy/explanation questions to Knowledge Assistant.
- Add MLflow traces for the agent path, similar to the bee pollinator demo walkthrough.
- Add richer patron behavior, promotions/free play, and TITO redemption aging.
- Add a scenario editor for demo presenters.

## Open Product Choices

These do not block the next phase, but should be decided before building:

- Whether to implement the simulator loop in TypeScript inside the AppKit server or use a separate Python process/job for long accelerated runs.
- Whether live multi-client viewing requires sampled patron positions in Lakebase or can rely on one active simulation controller.
- Whether the first implementation should include only Lakebase, or include analytics scaffolding from the start but leave Genie dormant.
- How detailed pathfinding needs to be before simple grid movement stops being convincing.

