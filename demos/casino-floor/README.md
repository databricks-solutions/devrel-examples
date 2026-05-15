# Casino Floor — Databricks demo

A small slot-floor telemetry demo: an agent-based simulator emits realistic
slot accounting events; a Databricks App replays the floor as a top-down
operator dashboard; an operations-manual corpus stands in for the Knowledge
Assistant; an analytics on-ramp documents the silver/gold tables Genie will
eventually answer questions against.

```
demos/casino-floor/
├── app/casino-floor/          AppKit (React + Express + Lakebase) Databricks App
│   ├── server/
│   │   ├── simulation/        tick simulator (~1k lines)
│   │   └── routes/            replay + docs API routes
│   ├── client/                React + Pixi.js floor canvas + dashboards
│   ├── shared/                shared types between client and server
│   ├── scripts/
│   │   ├── verify-run.ts      causal-consistency checker
│   │   └── export-run.ts      JSONL exporter for the silver/gold tables
│   └── package.json
├── data/
│   ├── manuals/               operations corpus (KA-ready markdown)
│   └── exports/<run_id>/      JSONL per analytics table per scenario
├── docs/
│   ├── analytics-tables.md    bronze/silver/gold schemas
│   └── genie-starter-queries.sql   the 12 SCOPING.md questions as SQL
├── scripts/
│   └── run-genie-queries.sh   register exported JSONL as duckdb views + run queries
├── SCOPING.md                 the original product/data design artifact
├── ABM_RESEARCH.md            agent-based-modeling tradeoffs
└── VISUAL_DESIGN.md           Pixi/Tiled visual direction
```

## What the demo shows

A user opens `/` and sees:

- A **floor KPI strip**: coin-in, actual hold %, ex-jackpot hold %, active
  sessions / occupancy %, progressive jackpot pool, jackpots-to-date, faulted
  machine count.
- A **bank KPI strip**: per-bank coin-in, hold, active sessions (matches
  what the eventual `gold_bank_hourly` table will surface).
- A **Pixi top-down floor**: 20 slot machines in 4 banks, a Neon Bar, off-canvas
  spawn points so patrons visibly enter/exit through doorway tiles, 130 patrons
  with archetype-driven palettes walking aisle paths to slots, sessions,
  jackpots, faults — all driven by the tick simulator.
- A **scenario picker**: 5 seeded scenarios (Opening Night, Quiet Wednesday,
  Jackpot Storm, Fault-Heavy Shift, Paytable Update Mid-Shift) each with a
  distinct demo narrative.
- **Jump-to moment** pills per scenario so a presenter can land on the story
  beat without scrubbing.
- An **inspector** that shows either:
  - A **machine PAR card** with theme, paytable_id, denom, volatility, theo
    vs actual hold (flagged when >3% off, with a "CONFIG CHANGED" badge if
    the machine has been swapped mid-shift), live meters, occupancy, recent
    activity. Reflects the *current* paytable, not just the initial one.
  - A **patron card** with archetype, wallet/bankroll, totals (bets, coin-in,
    coin-out, cash-in, ticket-out, bar visits), net result, and a full
    session history (machine, duration, net, ended reason).
- A **machine occupancy grid** in the sidebar (4×5) color-coded: green = in
  session, gray = idle, amber = soft fault, rose = hard fault, **purple flash**
  on recent CONFIG_CHANGE, **cyan flash** on recent JACKPOT.
- A **patron archetype counter**, a **nearby events** feed, a **floor status
  alerts** panel.

A second `/docs` route serves the operations corpus (PAR sheet template, bill
validator troubleshooting, progressive rules, maintenance log template, floor
narratives anomaly playbook) as a left-list / right-content reader. This is
where the Knowledge Assistant will eventually plug in.

## The simulator

`app/casino-floor/server/simulation/casino-simulator.ts` is a deterministic
seeded tick loop. Each scenario specifies a config; running `simulate(config,
machines)` produces position samples, an event log, and meter polls.

Patron archetypes: **High Roller**, **Jackpot Chaser**, **Grinder**, **Bar
Hopper**, **Window Shopper**, **Pass Through**, **Casual Player** — each with
distinct bankroll / volatility preference / bet cadence / bar affinity.

Patron lifecycle: OFFSCREEN → WALKING_TO_SLOT → PLAYING_SLOT (with TITO cash-in
and rebuys) → WALKING_TO_BAR / EXITING (with TICKET_OUT). Mid-walk faults
re-target the patron. Bar visitors pick one of six stools so a wave doesn't
stack on a single seat.

Each spin contributes to a shared progressive pool; a jackpot pays the pool
and resets to a $100 seed. Per-spin payouts have a mean-1.0 multiplier
(`(0.4 + rng()*1.2) × avgMultiplierIfHit`) so long-run RTP lands on the
configured value instead of the original `(0.4 + rng()*1.4)` bias of +10pp.

Aisle routing via `planRoute()`: when start/target span multiple zones,
patrons route through one of three vertical aisles (`x=3.5 / 12.85 / 22.0`)
and a horizontal corridor (`y=3.2 / 7.5 / 17.0`) chosen based on whether
endpoints sit near the top, middle, or bottom of the floor.

Event vocabulary (matches SCOPING.md):

- `SESSION_START`, `SESSION_END` (with `reason`: wallet_depleted /
  planned_end / machine_fault)
- `BET_SETTLED` with full accounting payload (coin_in_delta_cents,
  coin_out_delta_cents, jackpot_handpay_delta_cents,
  progressive_contribution_cents, progressive_pool_after_cents,
  theoretical_hold_pct, paytable_id, denomination_cents, volatility)
- `JACKPOT_HANDPAY` (same payload, with jackpot_handpay_cents > 0)
- `CASH_IN` (bill_in_delta_cents)
- `TICKET_OUT` (voucher_out_delta_cents)
- `MACHINE_STATUS` (status transitions: SOFT_FAULT, BILL_VALIDATOR_FAULT,
  DOOR_OPEN, OUT_OF_SERVICE → IN_SERVICE)
- `METER_POLL` every 30 sim-seconds (absolute counters)
- `CONFIG_CHANGE` (paytable swap mid-run)
- `BAR_VISIT`

## Scenarios

| Run | Story |
| --- | --- |
| Opening Night | 130 patrons, standard mix, one bill-validator fault on slot-008 |
| Quiet Wednesday | 70 patrons — variance dominates at low volume |
| Jackpot Storm | jackpotMultiplier = 3, ~3× the jackpots so the pool resets visibly |
| Fault-Heavy Shift | faultRate ramped — watch session abandonment and traffic shift |
| Paytable Update Mid-Shift | CONFIG_CHANGE at t=60s on slot-005 (PAR-925 LOW 5.4% → PAR-905 HIGH 9.5%) |

Each scenario seeds with a distinct PRNG, so runs are reproducible. The boot
seeds-once-then-skips by default; set `FORCE_RESEED=1` to regenerate.

## Verifying a run

```bash
cd app/casino-floor
npm run verify -- demo-run-005-config-change
```

Checks: every BET_SETTLED has an active SESSION_START before any matching
SESSION_END, jackpot eligibility (LOW machines never emit JACKPOT_HANDPAY,
respecting CONFIG_CHANGE volatility upgrades), no negative meters, meter
reconciliation gap (event-summed coin-in vs latest poll meter within ±2%
tolerance), fault-state hygiene (any non-IN_SERVICE machine at run end is
flagged as a warning so it doesn't slip through).

## Exporting analytics-ready data

```bash
cd app/casino-floor
npm run export -- demo-run-001
# → ../../data/exports/demo-run-001/{bronze,silver,gold}_*.jsonl
```

The exporter produces one JSONL per table — schemas documented in
`docs/analytics-tables.md`. With the exports in place, the duckdb runner

```bash
./scripts/run-genie-queries.sh demo-run-005-config-change
```

registers each JSONL as a view and runs the 12 starter queries from
`docs/genie-starter-queries.sql`. These are the SQL forms of the SCOPING.md
operator questions, ready for the future Genie space.

## Anomaly candidates

`gold_anomaly_candidates.jsonl` is populated by the exporter and surfaces
the six anomaly narratives from `data/manuals/floor-narratives.md`:

- `LOW_COIN_IN_FALSE_POSITIVE` — large hold gap at low coin-in
- `JACKPOT_DISTORTED_HOLD` — deeply negative raw hold but ex-jackpot hold
  near theoretical
- `METER_RECONCILIATION_GAP` — event-summed coin-in vs meter coin-in delta
- `FAULT_RATE_SPIKE` — bank fault minutes > 2× floor average
- `CONFIG_CHANGE_BASELINE_SHIFT` — a paytable swap occurred in this window

Typical output for `demo-run-005-config-change`:

```
JACKPOT_DISTORTED_HOLD     slot-013  bank-c  info
CONFIG_CHANGE_BASELINE_SHIFT slot-005  bank-a  info
LOW_COIN_IN_FALSE_POSITIVE × 9   (because 150s isn't long enough for hold
                                 to converge on most machines)
```

## Running the app

Prereqs: Node 22+, npm, the Databricks CLI configured for a workspace with
Lakebase access.

```bash
cd app/casino-floor
cp .env.example .env  # populate the Lakebase / Databricks vars
npm install
npm run dev           # http://localhost:8000
```

On boot the server seeds the 5 scenarios into Lakebase (idempotent by default;
`FORCE_RESEED=1 npm run dev` to regenerate).

## Architecture and decisions

See:

- [`SCOPING.md`](./SCOPING.md) — the original product / data / regulatory
  framing for the demo.
- [`ABM_RESEARCH.md`](./ABM_RESEARCH.md) — agent-based-modeling tradeoffs;
  current implementation is a TypeScript tick simulator in the AppKit server
  (the Mesa-first path described there is for the long-horizon variant later).
- [`VISUAL_DESIGN.md`](./VISUAL_DESIGN.md) — Pixi + Tiled rationale.
- [`docs/analytics-tables.md`](./docs/analytics-tables.md) — the silver/gold
  schemas.
- [`docs/genie-starter-queries.sql`](./docs/genie-starter-queries.sql) — the
  12 starter queries.
- [`data/manuals/`](./data/manuals/) — the operations corpus.

## Not yet built

- Delta export job (the schemas and JSONL exports document the contract).
- Genie space (queries are drafted and tested against the JSONL).
- Knowledge Assistant over the manuals corpus.
- Supervisor Agent routing structured ↔ policy questions.
- Sprite-atlas patron animation (current renders are bespoke `Graphics`
  shapes with per-patron palette + walking cycle).
- Long-horizon scenarios (multi-hour / multi-day).

Each of these has a clear seam in the current code — when they're added, the
existing simulator + verifier + export pipeline is the substrate.
