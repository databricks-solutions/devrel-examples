# Analytics tables — schemas

The tick simulator (in `app/casino-floor/server/simulation/casino-simulator.ts`)
already emits accounting-shaped events; the tables below are the shapes that
event stream is meant to land in once a Delta export job is wired up.

Until Delta is in place, `scripts/export-run.ts` produces JSONL files that
match these schemas exactly, so Genie SQL queries can be drafted and tested
against real-shaped data.

All money values are integer **cents**. All timestamps are real wall-clock
timestamps; `sim_second` is also retained so an analyst can join back to a
replay.

## Bronze

### `bronze_slot_events`

One row per emitted event. Raw, append-only.

| Column | Type | Description |
| --- | --- | --- |
| `event_id` | STRING | `${run_id}-${type}-${seq}` |
| `run_id` | STRING | FK to `simulation_runs` |
| `event_ts` | TIMESTAMP | Wall-clock time |
| `sim_second` | DOUBLE | Simulation second |
| `event_type` | STRING | One of `SESSION_START`, `SESSION_END`, `BET_SETTLED`, `JACKPOT_HANDPAY`, `CASH_IN`, `TICKET_OUT`, `MACHINE_STATUS`, `METER_POLL`, `CONFIG_CHANGE`, `BAR_VISIT` |
| `entity_id` | STRING | Machine OR patron, depending on event |
| `patron_id` | STRING | Nullable |
| `machine_id` | STRING | Nullable |
| `bank_id` | STRING | Cached for query convenience |
| `payload` | STRING (JSON) | Type-specific fields; see below |

The `payload` shape per event type:

```
SESSION_START      { session_id, theme, volatility, denomination_cents, paytable_id, theoretical_hold_pct, wallet_cents, credit_cents }
SESSION_END        { session_id, reason, wallet_cents, ticket_out_cents, duration_seconds }
BET_SETTLED        { session_id, bet_cents, win_cents, jackpot_handpay_cents, progressive_contribution_cents,
                     coin_in_delta_cents, coin_out_delta_cents, jackpot_handpay_delta_cents, progressive_pool_after_cents,
                     theoretical_hold_pct, paytable_id, denomination_cents, volatility }
JACKPOT_HANDPAY    same shape as BET_SETTLED with jackpot_handpay_cents > 0
CASH_IN            { session_id, bill_in_delta_cents, kind? }
TICKET_OUT         { session_id, voucher_out_delta_cents }
MACHINE_STATUS     { status, previous_status?, expected_clear_at? }
METER_POLL         { coin_in_cents, coin_out_cents, jackpot_handpay_cents, progressive_contribution_cents,
                     bill_in_cents, voucher_in_cents, voucher_out_cents, games_played }
CONFIG_CHANGE      { previous: { paytable_id, theoretical_hold_pct, volatility },
                     paytable_id, theoretical_hold_pct, volatility }
BAR_VISIT          { wallet_cents }
```

## Silver

### `silver_slot_spins`

One row per `BET_SETTLED` or `JACKPOT_HANDPAY` event. Normalized for hold/volatility
analysis.

| Column | Type | Description |
| --- | --- | --- |
| `event_id` | STRING | |
| `run_id` | STRING | |
| `event_ts` | TIMESTAMP | |
| `sim_second` | DOUBLE | |
| `machine_id` | STRING | |
| `bank_id` | STRING | |
| `session_id` | STRING | |
| `patron_id` | STRING | |
| `paytable_id` | STRING | At time of spin (respects CONFIG_CHANGE) |
| `theoretical_hold_pct` | DOUBLE | At time of spin |
| `volatility` | STRING | LOW / MEDIUM / HIGH at time of spin |
| `denomination_cents` | INTEGER | |
| `bet_cents` | INTEGER | |
| `win_cents` | INTEGER | Regular machine-paid win |
| `jackpot_handpay_cents` | INTEGER | Hand-paid progressive, separate from regular |
| `progressive_contribution_cents` | INTEGER | This spin's contribution to the pool |
| `progressive_pool_after_cents` | INTEGER | Pool meter after this spin (post-payout if jackpot) |
| `is_jackpot` | BOOLEAN | `jackpot_handpay_cents > 0` |

### `silver_meter_polls`

One row per machine per poll. Absolute counters plus deltas vs previous poll.

| Column | Type | Description |
| --- | --- | --- |
| `run_id` | STRING | |
| `sim_second` | DOUBLE | |
| `machine_id` | STRING | |
| `bank_id` | STRING | |
| `coin_in_cents` | BIGINT | Absolute |
| `coin_out_cents` | BIGINT | Absolute |
| `bill_in_cents` | BIGINT | Absolute |
| `voucher_in_cents` | BIGINT | Absolute |
| `voucher_out_cents` | BIGINT | Absolute |
| `jackpot_handpay_cents` | BIGINT | Absolute |
| `games_played` | BIGINT | Absolute |
| `coin_in_delta_cents` | BIGINT | vs previous poll |
| `coin_out_delta_cents` | BIGINT | vs previous poll |
| `jackpot_handpay_delta_cents` | BIGINT | vs previous poll |
| `games_delta` | BIGINT | vs previous poll |

### `silver_machine_status`

One row per `MACHINE_STATUS` transition.

| Column | Type | Description |
| --- | --- | --- |
| `run_id` | STRING | |
| `machine_id` | STRING | |
| `bank_id` | STRING | |
| `entered_at_sim_second` | DOUBLE | |
| `cleared_at_sim_second` | DOUBLE | NULL if status hasn't cleared by run end |
| `duration_seconds` | DOUBLE | NULL if open |
| `status` | STRING | SOFT_FAULT / BILL_VALIDATOR_FAULT / DOOR_OPEN / OUT_OF_SERVICE |
| `previous_status` | STRING | |
| `expected_clear_at_sim_second` | DOUBLE | NULL if not provided |

### `silver_patron_sessions`

One row per machine session.

| Column | Type | Description |
| --- | --- | --- |
| `session_id` | STRING | |
| `run_id` | STRING | |
| `machine_id` | STRING | |
| `bank_id` | STRING | |
| `patron_id` | STRING | |
| `started_at_sim_second` | DOUBLE | |
| `ended_at_sim_second` | DOUBLE | NULL if session still open at run end |
| `duration_seconds` | DOUBLE | |
| `total_coin_in_cents` | BIGINT | |
| `total_coin_out_cents` | BIGINT | |
| `total_jackpot_handpay_cents` | BIGINT | |
| `net_result_cents` | BIGINT | `coin_in - coin_out - jackpot_handpay` (machine perspective) |
| `bet_count` | INTEGER | |
| `cash_in_cents` | BIGINT | Sum of CASH_IN events on this session |
| `ticket_out_cents` | BIGINT | TICKET_OUT amount at session end |
| `ended_reason` | STRING | `wallet_depleted` / `planned_end` / `machine_fault` |
| `visited_bar_before` | BOOLEAN | Did the patron emit a BAR_VISIT before this session? |
| `visited_bar_after` | BOOLEAN | Did the patron emit a BAR_VISIT after this session ended? |

## Gold

### `gold_machine_daily`

Per-machine, per-day rollup (in the demo, "day" = one run).

| Column | Type | Description |
| --- | --- | --- |
| `run_id` | STRING | |
| `machine_id` | STRING | |
| `bank_id` | STRING | |
| `volatility` | STRING | At end of run (post-CONFIG_CHANGE if any) |
| `coin_in_cents` | BIGINT | |
| `coin_out_cents` | BIGINT | |
| `jackpot_handpay_cents` | BIGINT | |
| `actual_win_cents` | BIGINT | `coin_in - coin_out - jackpot_handpay` |
| `actual_hold_pct` | DOUBLE | |
| `theoretical_hold_pct` | DOUBLE | Time-weighted across CONFIG_CHANGE windows |
| `theoretical_win_cents` | BIGINT | `coin_in × theoretical_hold` |
| `hold_variance_bps` | DOUBLE | `(actual - theo) × 10000` |
| `games_played` | BIGINT | |
| `bet_count` | BIGINT | |
| `session_count` | INTEGER | |
| `uptime_seconds` | DOUBLE | Time spent in `IN_SERVICE` |
| `uptime_pct` | DOUBLE | |
| `fault_count` | INTEGER | |
| `fault_minutes` | DOUBLE | |

### `gold_bank_hourly`

Per-bank, per-hour rollup. For the demo's short runs, "hour" = full run window.

| Column | Type | Description |
| --- | --- | --- |
| `run_id` | STRING | |
| `bank_id` | STRING | |
| `hour_bucket` | TIMESTAMP | |
| `active_session_count` | INTEGER | Average across the bucket |
| `occupancy_pct` | DOUBLE | `active_sessions / machine_count` |
| `coin_in_cents` | BIGINT | |
| `actual_hold_pct` | DOUBLE | |
| `jackpot_adjusted_hold_pct` | DOUBLE | `(coin_in - coin_out) / coin_in` |
| `bar_adjacent_visits` | INTEGER | BAR_VISIT events while bank had ≥1 active session |
| `fault_minutes` | DOUBLE | |

### `gold_anomaly_candidates`

Precomputed flags + context. One row per anomaly per machine per window.

| Column | Type | Description |
| --- | --- | --- |
| `run_id` | STRING | |
| `flag` | STRING | `LOW_COIN_IN_FALSE_POSITIVE` / `HOLD_DRIFT_AFTER_VOLUME` / `METER_RECONCILIATION_GAP` / `FAULT_RATE_SPIKE` / `JACKPOT_DISTORTED_HOLD` / `CONFIG_CHANGE_BASELINE_SHIFT` / `OCCUPANCY_MIX_SHIFT` |
| `severity` | STRING | `info` / `warning` / `alert` |
| `machine_id` | STRING | Nullable for bank/floor-level flags |
| `bank_id` | STRING | Nullable for floor-level flags |
| `window_start_sim_second` | DOUBLE | |
| `window_end_sim_second` | DOUBLE | |
| `context` | STRING (JSON) | Type-specific details |
| `evidence_event_ids` | ARRAY<STRING> | Event IDs that triggered the flag |

### `gold_progressive_summary`

Progressive bank state over time.

| Column | Type | Description |
| --- | --- | --- |
| `run_id` | STRING | |
| `seed_cents` | BIGINT | |
| `final_meter_cents` | BIGINT | Pool value at end of run |
| `hit_count` | INTEGER | Number of jackpot pay-outs in the run |
| `total_handpay_cents` | BIGINT | Sum of jackpot pay-outs |
| `eligible_coin_in_cents` | BIGINT | Sum of bets that contributed |
| `contribution_rate_pct` | DOUBLE | `(sum of contributions) / coin_in × 100` |
| `mean_seconds_between_hits` | DOUBLE | |

## How to refresh sample data

```bash
# from app/casino-floor/
npx tsx scripts/export-run.ts demo-run-001 ../../data/exports/demo-run-001/
```

The exporter writes one `.jsonl` per table into the target directory. Repeat
per run_id to populate a Genie-ready sandbox.

## Genie starter questions

Once these tables exist in Delta, Genie should be able to handle the
operator-level questions documented in `SCOPING.md`, including:

1. Which machines had the largest gap between actual hold and theoretical hold,
   filtered to those with enough coin-in for the gap to be meaningful?
2. What is the jackpot-adjusted hold by bank for the last hour?
3. Which machines have meter reconciliation gaps between event deltas and
   meter polls?
4. Show fault minutes per machine vs. its neighbors' coin-in.
5. After the CONFIG_CHANGE at sim_second=60, did the new paytable's
   actual hold converge toward the new theoretical?
