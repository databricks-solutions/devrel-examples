-- Genie starter queries
--
-- These are the 12 starter questions from SCOPING.md, drafted as SQL and
-- verified against the JSONL exports in `data/exports/<runId>/` using duckdb.
-- They are the seed for a Genie space's curated query library once the Delta
-- tables exist.
--
-- To run any query against a run:
--
--   cd demos/casino-floor
--   duckdb -c "
--     CREATE VIEW silver_slot_spins AS
--       SELECT * FROM read_json_auto('data/exports/demo-run-001/silver_slot_spins.jsonl');
--     CREATE VIEW gold_machine_daily AS
--       SELECT * FROM read_json_auto('data/exports/demo-run-001/gold_machine_daily.jsonl');
--     -- ... etc per table ...
--   " < docs/genie-starter-queries.sql
--
-- `scripts/run-genie-queries.sh` wraps that pattern for all 5 scenarios.

-- ─── Q1 ─────────────────────────────────────────────────────────────────
-- Which five machines had the largest gap between actual hold and theoretical
-- hold today (this run)?
SELECT
  machine_id,
  volatility,
  ROUND(actual_hold_pct, 2)         AS actual_hold_pct,
  ROUND(theoretical_hold_pct, 2)    AS theo_hold_pct,
  ROUND(hold_variance_bps / 100, 2) AS variance_pct,
  coin_in_cents / 100.0             AS coin_in_dollars,
  games_played
FROM gold_machine_daily
WHERE coin_in_cents > 0
ORDER BY ABS(hold_variance_bps) DESC
LIMIT 5;

-- ─── Q2 ─────────────────────────────────────────────────────────────────
-- Of those machines, which have enough coin-in for the gap to be meaningful?
-- (Operator rule of thumb: HIGH-volatility machines need ~$100 of coin-in
-- before short-run hold means anything; MEDIUM ~$50; LOW ~$25.)
WITH thresholds AS (
  SELECT 'LOW' AS volatility, 2500 AS min_coin_in_cents UNION ALL
  SELECT 'MEDIUM',           5000 UNION ALL
  SELECT 'HIGH',            10000
)
SELECT
  m.machine_id,
  m.volatility,
  ROUND(m.actual_hold_pct, 2)        AS actual_hold_pct,
  ROUND(m.theoretical_hold_pct, 2)   AS theo_hold_pct,
  m.coin_in_cents / 100.0            AS coin_in_dollars,
  t.min_coin_in_cents / 100.0        AS min_meaningful_coin_in_dollars,
  CASE
    WHEN m.coin_in_cents >= t.min_coin_in_cents THEN 'sufficient'
    ELSE 'low volume — interpret with caution'
  END AS volume_assessment
FROM gold_machine_daily m
JOIN thresholds t USING (volatility)
WHERE m.coin_in_cents > 0
ORDER BY ABS(m.hold_variance_bps) DESC
LIMIT 5;

-- ─── Q3 ─────────────────────────────────────────────────────────────────
-- Show actual hold versus theoretical hold by bank for the last simulated
-- hour. (Demo runs are 150–180s, so "hour" = full run window.)
SELECT
  bank_id,
  COUNT(*)                                         AS machine_count,
  SUM(coin_in_cents) / 100.0                       AS coin_in_dollars,
  SUM(coin_out_cents) / 100.0                      AS coin_out_dollars,
  SUM(jackpot_handpay_cents) / 100.0               AS jackpot_pay_dollars,
  ROUND(
    100.0 * (SUM(coin_in_cents) - SUM(coin_out_cents) - SUM(jackpot_handpay_cents))
    / NULLIF(SUM(coin_in_cents), 0),
    2
  ) AS actual_hold_pct,
  ROUND(
    100.0 * (SUM(coin_in_cents) - SUM(coin_out_cents))
    / NULLIF(SUM(coin_in_cents), 0),
    2
  ) AS jackpot_adjusted_hold_pct,
  ROUND(AVG(theoretical_hold_pct), 2) AS theo_hold_pct_avg
FROM gold_machine_daily
GROUP BY bank_id
ORDER BY bank_id;

-- ─── Q4 ─────────────────────────────────────────────────────────────────
-- Which machine looks anomalous before jackpot adjustment but normal after
-- excluding jackpot hand pays?
SELECT
  machine_id,
  bank_id,
  volatility,
  coin_in_cents / 100.0                                       AS coin_in_dollars,
  jackpot_handpay_cents / 100.0                               AS jackpot_pay_dollars,
  ROUND(actual_hold_pct, 2)                                   AS actual_hold_pct,
  ROUND(
    100.0 * (coin_in_cents - coin_out_cents)
    / NULLIF(coin_in_cents, 0),
    2
  ) AS jackpot_adjusted_hold_pct,
  ROUND(theoretical_hold_pct, 2) AS theo_hold_pct
FROM gold_machine_daily
WHERE coin_in_cents > 0
  AND jackpot_handpay_cents > 0
  AND ABS(actual_hold_pct - theoretical_hold_pct) > 20
  AND ABS(
        100.0 * (coin_in_cents - coin_out_cents) / NULLIF(coin_in_cents, 0)
        - theoretical_hold_pct
      ) < 10
ORDER BY ABS(actual_hold_pct - theoretical_hold_pct) DESC;

-- ─── Q5 ─────────────────────────────────────────────────────────────────
-- Did any machines have meter reconciliation gaps between event deltas and
-- meter polls?
WITH machine_event_totals AS (
  SELECT
    machine_id,
    SUM(bet_cents) AS event_coin_in_cents
  FROM silver_slot_spins
  GROUP BY machine_id
),
machine_meter_latest AS (
  SELECT
    machine_id,
    MAX_BY(coin_in_cents, sim_second) AS meter_coin_in_cents
  FROM silver_meter_polls
  GROUP BY machine_id
)
SELECT
  m.machine_id,
  e.event_coin_in_cents,
  m.meter_coin_in_cents,
  m.meter_coin_in_cents - e.event_coin_in_cents AS gap_cents,
  ROUND(
    100.0 * (m.meter_coin_in_cents - e.event_coin_in_cents)
    / NULLIF(e.event_coin_in_cents, 0),
    2
  ) AS gap_pct
FROM machine_meter_latest m
LEFT JOIN machine_event_totals e USING (machine_id)
WHERE ABS(m.meter_coin_in_cents - COALESCE(e.event_coin_in_cents, 0)) > 50
ORDER BY ABS(gap_cents) DESC;

-- ─── Q6 ─────────────────────────────────────────────────────────────────
-- Which machines had the most fault minutes, and how much coin-in did they
-- lose compared with nearby machines (same bank)?
WITH fault_minutes AS (
  SELECT
    machine_id,
    bank_id,
    SUM(COALESCE(duration_seconds, 0)) / 60.0 AS fault_minutes
  FROM silver_machine_status
  GROUP BY machine_id, bank_id
),
machine_coin_in AS (
  SELECT machine_id, bank_id, coin_in_cents
  FROM gold_machine_daily
),
bank_avg_coin_in AS (
  SELECT bank_id, AVG(coin_in_cents) AS bank_avg_coin_in_cents
  FROM machine_coin_in
  GROUP BY bank_id
)
SELECT
  f.machine_id,
  f.bank_id,
  ROUND(f.fault_minutes, 2)                          AS fault_minutes,
  m.coin_in_cents / 100.0                            AS coin_in_dollars,
  ROUND(b.bank_avg_coin_in_cents / 100.0, 2)         AS bank_avg_coin_in_dollars,
  ROUND(
    100.0 * (m.coin_in_cents - b.bank_avg_coin_in_cents)
    / NULLIF(b.bank_avg_coin_in_cents, 0),
    2
  ) AS pct_vs_bank_avg
FROM fault_minutes f
JOIN machine_coin_in m USING (machine_id, bank_id)
JOIN bank_avg_coin_in b USING (bank_id)
WHERE f.fault_minutes > 0
ORDER BY f.fault_minutes DESC;

-- ─── Q7 ─────────────────────────────────────────────────────────────────
-- Did the flaky bill validator reduce play, or did patrons move to other
-- machines in the same bank? Compare bank-B (with the seeded fault) vs the
-- machine's own pre-fault baseline.
WITH faulted AS (
  SELECT machine_id, entered_at_sim_second, cleared_at_sim_second
  FROM silver_machine_status
  WHERE status = 'BILL_VALIDATOR_FAULT'
),
bank_of AS (
  SELECT machine_id, bank_id FROM silver_meter_polls GROUP BY machine_id, bank_id
)
SELECT
  f.machine_id                                                AS faulted_machine,
  f.entered_at_sim_second,
  f.cleared_at_sim_second,
  -- Coin-in on the faulted machine during the fault window
  (SELECT SUM(bet_cents)
     FROM silver_slot_spins s
     WHERE s.machine_id = f.machine_id
       AND s.sim_second BETWEEN f.entered_at_sim_second AND COALESCE(f.cleared_at_sim_second, 9999)
  ) / 100.0 AS faulted_coin_in_during_dollars,
  -- Coin-in on neighbors in the same bank during the same window
  (SELECT SUM(s.bet_cents)
     FROM silver_slot_spins s
     JOIN bank_of b USING (machine_id)
     JOIN bank_of bf ON bf.machine_id = f.machine_id
     WHERE b.bank_id = bf.bank_id
       AND s.machine_id != f.machine_id
       AND s.sim_second BETWEEN f.entered_at_sim_second AND COALESCE(f.cleared_at_sim_second, 9999)
  ) / 100.0 AS neighbors_coin_in_during_dollars
FROM faulted f;

-- ─── Q8 ─────────────────────────────────────────────────────────────────
-- Which machines had a configuration or paytable change, and how did their
-- baseline theoretical hold change?
WITH bet_buckets AS (
  SELECT
    machine_id,
    paytable_id,
    volatility,
    theoretical_hold_pct,
    SUM(bet_cents)                  AS coin_in_cents,
    SUM(win_cents)                  AS coin_out_cents,
    SUM(jackpot_handpay_cents)      AS jackpot_pay_cents,
    COUNT(*)                        AS bet_count,
    MIN(sim_second)                 AS first_seen,
    MAX(sim_second)                 AS last_seen
  FROM silver_slot_spins
  GROUP BY machine_id, paytable_id, volatility, theoretical_hold_pct
),
distinct_paytables AS (
  SELECT machine_id, COUNT(DISTINCT paytable_id) AS paytable_count
  FROM bet_buckets
  GROUP BY machine_id
)
SELECT
  b.machine_id,
  b.paytable_id,
  b.volatility,
  ROUND(b.theoretical_hold_pct, 2) AS theo_hold_pct,
  ROUND(b.first_seen, 1)           AS first_sec,
  ROUND(b.last_seen, 1)            AS last_sec,
  b.bet_count,
  b.coin_in_cents / 100.0          AS coin_in_dollars,
  ROUND(
    100.0 * (b.coin_in_cents - b.coin_out_cents - b.jackpot_pay_cents)
    / NULLIF(b.coin_in_cents, 0),
    2
  ) AS actual_hold_pct
FROM bet_buckets b
JOIN distinct_paytables d USING (machine_id)
WHERE d.paytable_count > 1
ORDER BY b.machine_id, b.first_seen;

-- ─── Q9 ─────────────────────────────────────────────────────────────────
-- How much of the floor's win came from high-volatility machines versus
-- low-volatility machines?
SELECT
  volatility,
  COUNT(*)                                       AS machine_count,
  SUM(coin_in_cents) / 100.0                     AS coin_in_dollars,
  SUM(actual_win_cents) / 100.0                  AS actual_win_dollars,
  ROUND(
    100.0 * SUM(actual_win_cents)
    / NULLIF((SELECT SUM(actual_win_cents) FROM gold_machine_daily), 0),
    2
  ) AS pct_of_floor_win
FROM gold_machine_daily
GROUP BY volatility
ORDER BY pct_of_floor_win DESC;

-- ─── Q10 ────────────────────────────────────────────────────────────────
-- Did bar visits increase session duration or coin-in for adjacent machines?
-- "Adjacent" in the demo = machines within 5 sim seconds of a BAR_VISIT
-- event by the same patron.
SELECT
  CASE
    WHEN visited_bar_before OR visited_bar_after THEN 'with bar visit'
    ELSE 'no bar visit'
  END                                              AS cohort,
  COUNT(*)                                         AS sessions,
  ROUND(AVG(duration_seconds), 1)                  AS avg_duration_seconds,
  ROUND(AVG(total_coin_in_cents) / 100.0, 2)       AS avg_coin_in_dollars,
  ROUND(AVG(bet_count), 1)                         AS avg_bets
FROM silver_patron_sessions
WHERE duration_seconds IS NOT NULL
GROUP BY cohort
ORDER BY cohort;

-- ─── Q11 ────────────────────────────────────────────────────────────────
-- Which anomaly candidates are likely normal variance due to low sample
-- size? Heuristic: hold gap > 15pp AND coin-in < $25.
SELECT
  machine_id,
  bank_id,
  volatility,
  coin_in_cents / 100.0          AS coin_in_dollars,
  games_played,
  ROUND(actual_hold_pct, 2)      AS actual_hold_pct,
  ROUND(theoretical_hold_pct, 2) AS theo_hold_pct,
  ROUND(
    actual_hold_pct - theoretical_hold_pct,
    2
  )                              AS gap_pct,
  'LOW_COIN_IN_FALSE_POSITIVE'   AS flag
FROM gold_machine_daily
WHERE coin_in_cents > 0
  AND coin_in_cents < 2500
  AND ABS(actual_hold_pct - theoretical_hold_pct) > 15
ORDER BY ABS(actual_hold_pct - theoretical_hold_pct) DESC;

-- Once the silver/gold tables exist in Delta, register this file as the
-- starter query library for the Genie space. Each section heading maps to
-- one of the SCOPING.md questions, so an operator who asks
-- "show me the largest hold gaps" can be routed to Q1, etc.

-- ─── Q12 ────────────────────────────────────────────────────────────────
-- What changed in bank C after the progressive jackpot hit? Compare 30-second
-- coin-in and session count before vs after the most-recent JACKPOT_HANDPAY
-- attributed to bank-c.
WITH jackpot_hit AS (
  SELECT s.sim_second AS hit_sec
  FROM silver_slot_spins s
  WHERE s.is_jackpot AND s.bank_id = 'bank-c'
  ORDER BY s.sim_second DESC
  LIMIT 1
)
SELECT
  CASE WHEN s.sim_second < h.hit_sec THEN 'before' ELSE 'after' END AS phase,
  COUNT(*)                                  AS bet_count,
  SUM(s.bet_cents) / 100.0                  AS coin_in_dollars,
  COUNT(DISTINCT s.session_id)              AS distinct_sessions
FROM silver_slot_spins s
CROSS JOIN jackpot_hit h
WHERE s.bank_id = 'bank-c'
  AND s.sim_second BETWEEN h.hit_sec - 30 AND h.hit_sec + 30
GROUP BY phase
ORDER BY phase;
