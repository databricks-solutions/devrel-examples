-- Casino Floor — silver/gold Delta views over Lakehouse Sync bronze
--
-- Apply after Lakehouse Sync starts producing tables in daniel_liden.casino_floor.
-- The bronze tables land as SCD Type 2 history with the naming pattern
-- `lb_<table_name>_history` and these system columns:
--
--   _pg_change_type   'insert' | 'delete' | 'update_preimage' | 'update_postimage'
--   _pg_lsn           BIGINT — Postgres LSN
--   _pg_xid           INTEGER — transaction id
--   _timestamp        TIMESTAMP — when the sync processed the change
--   _sort_by          BIGINT — monotonic ordering key
--
-- For the casino-floor schema specifically:
--   simulation_runs   ON CONFLICT UPDATE on (run_id) → may have multiple history rows per PK
--   floor_entities    ON CONFLICT UPDATE on (entity_id) → same
--   activity_events   append-only by event_id (no updates expected)
--   meter_polls       append-only (no PK in source; sync adds row identity)
--
-- We use a deduplication pattern per row: group by primary key, take max_by
-- of every other column over _sort_by, exclude deletes.

-- Apply with the Statement Execution API setting catalog=daniel_liden,
-- schema=casino_floor (the script loops over each statement individually).

-- ─── bronze (current state) views ───────────────────────────────────────
-- Filters SCD2 history down to the latest visible row per PK.

-- Note: Postgres NUMERIC, JSONB, and TIMESTAMPTZ all land in Delta as STRING
-- via the Lakehouse Sync (with the exception of true integer/timestamp types).
-- We cast NUMERIC → DOUBLE in bronze so downstream silver/gold can stay clean.

CREATE OR REPLACE VIEW bronze_simulation_runs AS
SELECT
  run_id,
  max_by(name,                       _sort_by) AS name,
  max_by(description,                _sort_by) AS description,
  max_by(starts_at,                  _sort_by) AS starts_at,
  max_by(duration_seconds,           _sort_by) AS duration_seconds,
  CAST(max_by(sample_rate_hz,        _sort_by) AS DOUBLE) AS sample_rate_hz,
  max_by(created_at,                 _sort_by) AS created_at
FROM lb_simulation_runs_history
GROUP BY run_id
HAVING max_by(_pg_change_type, _sort_by) IN ('insert', 'update_postimage');

CREATE OR REPLACE VIEW bronze_floor_entities AS
SELECT
  entity_id,
  max_by(entity_type, _sort_by)               AS entity_type,
  max_by(label,       _sort_by)               AS label,
  CAST(max_by(x,      _sort_by) AS DOUBLE)    AS x,
  CAST(max_by(y,      _sort_by) AS DOUBLE)    AS y,
  CAST(max_by(width,  _sort_by) AS DOUBLE)    AS width,
  CAST(max_by(height, _sort_by) AS DOUBLE)    AS height,
  max_by(metadata,    _sort_by)               AS metadata
FROM lb_floor_entities_history
GROUP BY entity_id
HAVING max_by(_pg_change_type, _sort_by) IN ('insert', 'update_postimage');

CREATE OR REPLACE VIEW bronze_activity_events AS
SELECT
  event_id,
  max_by(run_id,         _sort_by)             AS run_id,
  CAST(max_by(sim_second, _sort_by) AS DOUBLE) AS sim_second,
  max_by(event_type,     _sort_by)             AS event_type,
  max_by(entity_id,      _sort_by)             AS entity_id,
  max_by(patron_id,      _sort_by)             AS patron_id,
  max_by(machine_id,     _sort_by)             AS machine_id,
  max_by(title,          _sort_by)             AS title,
  max_by(description,    _sort_by)             AS description,
  max_by(payload,        _sort_by)             AS payload
FROM lb_activity_events_history
GROUP BY event_id
HAVING max_by(_pg_change_type, _sort_by) IN ('insert', 'update_postimage');

-- meter_polls has no surrogate PK in source; use (id) which lakebase added.
CREATE OR REPLACE VIEW bronze_meter_polls AS
SELECT
  id,
  max_by(run_id,         _sort_by)              AS run_id,
  CAST(max_by(sim_second, _sort_by) AS DOUBLE)  AS sim_second,
  max_by(machine_id,     _sort_by)              AS machine_id,
  max_by(meters,         _sort_by)              AS meters
FROM lb_meter_polls_history
GROUP BY id
HAVING max_by(_pg_change_type, _sort_by) IN ('insert', 'update_postimage');

-- ─── silver ─────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW silver_slot_spins
COMMENT 'One row per BET_SETTLED or JACKPOT_HANDPAY. Normalized for hold/volatility analysis; respects mid-shift CONFIG_CHANGE because paytable_id and volatility are pulled from the event payload (point-in-time correct).'
AS
WITH machine_banks AS (
  SELECT entity_id AS machine_id, metadata:bank_id::string AS bank_id
  FROM bronze_floor_entities
  WHERE entity_type = 'machine'
)
SELECT
  e.event_id,
  e.run_id,
  e.sim_second,
  e.machine_id,
  mb.bank_id,
  e.patron_id,
  e.payload:session_id::string                       AS session_id,
  e.payload:paytable_id::string                      AS paytable_id,
  CAST(e.payload:theoretical_hold_pct AS DOUBLE)     AS theoretical_hold_pct,
  e.payload:volatility::string                       AS volatility,
  CAST(e.payload:denomination_cents AS BIGINT)       AS denomination_cents,
  CAST(e.payload:bet_cents AS BIGINT)                AS bet_cents,
  CAST(e.payload:win_cents AS BIGINT)                AS win_cents,
  CAST(e.payload:jackpot_handpay_cents AS BIGINT)    AS jackpot_handpay_cents,
  CAST(e.payload:progressive_contribution_cents AS BIGINT) AS progressive_contribution_cents,
  CAST(e.payload:progressive_pool_after_cents AS BIGINT)   AS progressive_pool_after_cents,
  (e.event_type = 'JACKPOT_HANDPAY')                 AS is_jackpot
FROM bronze_activity_events e
LEFT JOIN machine_banks mb USING (machine_id)
WHERE e.event_type IN ('BET_SETTLED', 'JACKPOT_HANDPAY');

CREATE OR REPLACE VIEW silver_meter_polls
COMMENT 'One row per meter poll; absolute counters with per-machine deltas vs previous poll.'
AS
WITH base AS (
  SELECT
    p.run_id,
    p.sim_second,
    p.machine_id,
    p.meters,
    mb.bank_id
  FROM bronze_meter_polls p
  LEFT JOIN (
    SELECT entity_id AS machine_id, metadata:bank_id::string AS bank_id
    FROM bronze_floor_entities
    WHERE entity_type = 'machine'
  ) mb USING (machine_id)
),
typed AS (
  SELECT
    run_id, sim_second, machine_id, bank_id,
    CAST(meters:coin_in_cents AS BIGINT)             AS coin_in_cents,
    CAST(meters:coin_out_cents AS BIGINT)            AS coin_out_cents,
    CAST(meters:bill_in_cents AS BIGINT)             AS bill_in_cents,
    CAST(meters:voucher_in_cents AS BIGINT)          AS voucher_in_cents,
    CAST(meters:voucher_out_cents AS BIGINT)         AS voucher_out_cents,
    CAST(meters:jackpot_handpay_cents AS BIGINT)     AS jackpot_handpay_cents,
    CAST(meters:games_played AS BIGINT)              AS games_played
  FROM base
)
SELECT
  *,
  coin_in_cents - LAG(coin_in_cents) OVER w               AS coin_in_delta_cents,
  coin_out_cents - LAG(coin_out_cents) OVER w             AS coin_out_delta_cents,
  jackpot_handpay_cents - LAG(jackpot_handpay_cents) OVER w AS jackpot_handpay_delta_cents,
  games_played - LAG(games_played) OVER w                 AS games_delta
FROM typed
WINDOW w AS (PARTITION BY run_id, machine_id ORDER BY sim_second);

CREATE OR REPLACE VIEW silver_machine_status
COMMENT 'Each non-IN_SERVICE → IN_SERVICE pair becomes one row with duration. Open transitions (no clear by run end) have NULL cleared_at_sim_second.'
AS
WITH status_events AS (
  SELECT
    e.run_id,
    e.machine_id,
    e.sim_second,
    e.payload:status::string AS status,
    e.payload:previous_status::string AS previous_status,
    CAST(e.payload:expected_clear_at AS DOUBLE) AS expected_clear_at
  FROM bronze_activity_events e
  WHERE e.event_type = 'MACHINE_STATUS'
),
paired AS (
  SELECT
    run_id, machine_id, status, previous_status, expected_clear_at,
    sim_second AS entered_at_sim_second,
    LEAD(sim_second) OVER (PARTITION BY run_id, machine_id ORDER BY sim_second) AS next_event_sim_second,
    LEAD(status)     OVER (PARTITION BY run_id, machine_id ORDER BY sim_second) AS next_status
  FROM status_events
)
SELECT
  run_id,
  machine_id,
  status,
  entered_at_sim_second,
  CASE WHEN next_status = 'IN_SERVICE' THEN next_event_sim_second ELSE NULL END AS cleared_at_sim_second,
  CASE WHEN next_status = 'IN_SERVICE' THEN next_event_sim_second - entered_at_sim_second ELSE NULL END AS duration_seconds,
  previous_status,
  expected_clear_at AS expected_clear_at_sim_second
FROM paired
WHERE status != 'IN_SERVICE';

CREATE OR REPLACE VIEW silver_patron_sessions
COMMENT 'One row per machine session. Joins SESSION_START to SESSION_END and rolls up bets/cash/tickets/jackpots for the session.'
AS
WITH session_starts AS (
  SELECT
    e.payload:session_id::string AS session_id,
    e.run_id,
    e.machine_id,
    e.patron_id,
    e.sim_second AS started_at_sim_second
  FROM bronze_activity_events e
  WHERE e.event_type = 'SESSION_START'
),
session_ends AS (
  SELECT
    e.payload:session_id::string AS session_id,
    e.sim_second AS ended_at_sim_second,
    e.payload:reason::string AS ended_reason,
    CAST(e.payload:ticket_out_cents AS BIGINT) AS ticket_out_cents
  FROM bronze_activity_events e
  WHERE e.event_type = 'SESSION_END'
),
session_bets AS (
  SELECT
    e.payload:session_id::string AS session_id,
    SUM(CAST(e.payload:coin_in_delta_cents AS BIGINT))            AS total_coin_in_cents,
    SUM(CAST(e.payload:coin_out_delta_cents AS BIGINT))           AS total_coin_out_cents,
    SUM(CAST(e.payload:jackpot_handpay_delta_cents AS BIGINT))    AS total_jackpot_handpay_cents,
    COUNT(*) AS bet_count
  FROM bronze_activity_events e
  WHERE e.event_type IN ('BET_SETTLED', 'JACKPOT_HANDPAY')
  GROUP BY 1
),
session_cash AS (
  SELECT
    e.payload:session_id::string AS session_id,
    SUM(CAST(e.payload:bill_in_delta_cents AS BIGINT)) AS cash_in_cents
  FROM bronze_activity_events e
  WHERE e.event_type = 'CASH_IN'
  GROUP BY 1
),
machine_banks AS (
  SELECT entity_id AS machine_id, metadata:bank_id::string AS bank_id
  FROM bronze_floor_entities
  WHERE entity_type = 'machine'
),
patron_bar_visits AS (
  SELECT patron_id, sim_second
  FROM bronze_activity_events
  WHERE event_type = 'BAR_VISIT'
)
SELECT
  s.run_id,
  s.session_id,
  s.machine_id,
  mb.bank_id,
  s.patron_id,
  s.started_at_sim_second,
  ee.ended_at_sim_second,
  ee.ended_at_sim_second - s.started_at_sim_second AS duration_seconds,
  COALESCE(sb.total_coin_in_cents, 0)         AS total_coin_in_cents,
  COALESCE(sb.total_coin_out_cents, 0)        AS total_coin_out_cents,
  COALESCE(sb.total_jackpot_handpay_cents, 0) AS total_jackpot_handpay_cents,
  COALESCE(sb.total_coin_in_cents, 0) - COALESCE(sb.total_coin_out_cents, 0) - COALESCE(sb.total_jackpot_handpay_cents, 0) AS net_result_cents,
  COALESCE(sb.bet_count, 0)                   AS bet_count,
  COALESCE(sc.cash_in_cents, 0)               AS cash_in_cents,
  COALESCE(ee.ticket_out_cents, 0)            AS ticket_out_cents,
  ee.ended_reason,
  EXISTS (SELECT 1 FROM patron_bar_visits b WHERE b.patron_id = s.patron_id AND b.sim_second < s.started_at_sim_second) AS visited_bar_before,
  CASE WHEN ee.ended_at_sim_second IS NOT NULL THEN
    EXISTS (SELECT 1 FROM patron_bar_visits b WHERE b.patron_id = s.patron_id AND b.sim_second > ee.ended_at_sim_second)
  ELSE FALSE END AS visited_bar_after
FROM session_starts s
LEFT JOIN session_ends  ee USING (session_id)
LEFT JOIN session_bets  sb USING (session_id)
LEFT JOIN session_cash  sc USING (session_id)
LEFT JOIN machine_banks mb USING (machine_id);

-- ─── gold ───────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW gold_machine_daily
COMMENT 'Per-machine, per-run rollup. theoretical_hold_pct is time-weighted by coin-in so CONFIG_CHANGE windows are respected.'
AS
SELECT
  s.run_id,
  s.machine_id,
  s.bank_id,
  -- volatility at the *last* spin (post-CONFIG_CHANGE if any)
  max_by(s.volatility, s.sim_second)                            AS volatility,
  SUM(s.bet_cents)                                              AS coin_in_cents,
  SUM(s.win_cents)                                              AS coin_out_cents,
  SUM(s.jackpot_handpay_cents)                                  AS jackpot_handpay_cents,
  SUM(s.bet_cents) - SUM(s.win_cents) - SUM(s.jackpot_handpay_cents) AS actual_win_cents,
  CASE WHEN SUM(s.bet_cents) > 0 THEN
    (SUM(s.bet_cents) - SUM(s.win_cents) - SUM(s.jackpot_handpay_cents)) / SUM(s.bet_cents) * 100
  END                                                           AS actual_hold_pct,
  CASE WHEN SUM(s.bet_cents) > 0 THEN
    SUM(s.bet_cents * s.theoretical_hold_pct) / SUM(s.bet_cents)
  END                                                           AS theoretical_hold_pct,
  CAST(SUM(s.bet_cents * s.theoretical_hold_pct) / 100 AS BIGINT) AS theoretical_win_cents,
  COUNT(*)                                                      AS games_played,
  COUNT(*)                                                      AS bet_count,
  COUNT(DISTINCT s.session_id)                                  AS session_count
FROM silver_slot_spins s
GROUP BY s.run_id, s.machine_id, s.bank_id;

CREATE OR REPLACE VIEW gold_bank_hourly
COMMENT 'Per-bank, per-run rollup. For demo runs of 150–180s, this is one row per (run, bank) — extend to time buckets when long-horizon runs land.'
AS
SELECT
  s.run_id,
  s.bank_id,
  COUNT(DISTINCT s.machine_id) AS machine_count,
  SUM(s.bet_cents)             AS coin_in_cents,
  SUM(s.win_cents)             AS coin_out_cents,
  SUM(s.jackpot_handpay_cents) AS jackpot_handpay_cents,
  CASE WHEN SUM(s.bet_cents) > 0 THEN
    (SUM(s.bet_cents) - SUM(s.win_cents) - SUM(s.jackpot_handpay_cents)) / SUM(s.bet_cents) * 100
  END AS actual_hold_pct,
  CASE WHEN SUM(s.bet_cents) > 0 THEN
    (SUM(s.bet_cents) - SUM(s.win_cents)) / SUM(s.bet_cents) * 100
  END AS jackpot_adjusted_hold_pct,
  COUNT(DISTINCT s.session_id) AS session_count,
  SUM(CASE WHEN s.is_jackpot THEN 1 ELSE 0 END) AS jackpot_count
FROM silver_slot_spins s
WHERE s.bank_id IS NOT NULL
GROUP BY s.run_id, s.bank_id;

CREATE OR REPLACE VIEW gold_progressive_summary
COMMENT 'Progressive pool behavior per run. Eligible coin-in counts every spin; contribution_rate_pct should hover near 1.25%.'
AS
WITH jackpot_gaps AS (
  SELECT
    run_id,
    AVG(sim_second - prev_sim_second) AS mean_gap
  FROM (
    SELECT
      run_id,
      sim_second,
      LAG(sim_second) OVER (PARTITION BY run_id ORDER BY sim_second) AS prev_sim_second
    FROM silver_slot_spins
    WHERE is_jackpot
  )
  WHERE prev_sim_second IS NOT NULL
  GROUP BY run_id
),
agg AS (
  SELECT
    s.run_id,
    10000 AS seed_cents,
    CAST(max_by(s.progressive_pool_after_cents, s.sim_second) AS BIGINT) AS final_meter_cents,
    COUNT_IF(s.is_jackpot)                                               AS hit_count,
    SUM(s.jackpot_handpay_cents)                                         AS total_handpay_cents,
    SUM(s.bet_cents)                                                     AS eligible_coin_in_cents,
    CASE WHEN SUM(s.bet_cents) > 0 THEN
      SUM(s.progressive_contribution_cents) / SUM(s.bet_cents) * 100
    END                                                                  AS contribution_rate_pct
  FROM silver_slot_spins s
  GROUP BY s.run_id
)
SELECT
  agg.*,
  jg.mean_gap AS mean_seconds_between_hits
FROM agg
LEFT JOIN jackpot_gaps jg USING (run_id);

CREATE OR REPLACE VIEW gold_anomaly_candidates
COMMENT 'Operator-relevant flags: LOW_COIN_IN_FALSE_POSITIVE, JACKPOT_DISTORTED_HOLD, METER_RECONCILIATION_GAP, FAULT_RATE_SPIKE, CONFIG_CHANGE_BASELINE_SHIFT. Use the context map for severity details.'
AS
-- 1. LOW_COIN_IN_FALSE_POSITIVE: big gap at low volume
SELECT
  m.run_id,
  'LOW_COIN_IN_FALSE_POSITIVE' AS flag,
  'info' AS severity,
  m.machine_id,
  m.bank_id,
  map(
    'coin_in_cents',                m.coin_in_cents,
    'min_meaningful_coin_in_cents', CASE m.volatility WHEN 'LOW' THEN 2500 WHEN 'HIGH' THEN 10000 ELSE 5000 END,
    'actual_hold_pct',              CAST(m.actual_hold_pct AS BIGINT),
    'theoretical_hold_pct',         CAST(m.theoretical_hold_pct AS BIGINT)
  ) AS context
FROM gold_machine_daily m
WHERE m.coin_in_cents > 0
  AND m.coin_in_cents < CASE m.volatility WHEN 'LOW' THEN 2500 WHEN 'HIGH' THEN 10000 ELSE 5000 END
  AND ABS(m.actual_hold_pct - m.theoretical_hold_pct) > 15

UNION ALL
-- 2. JACKPOT_DISTORTED_HOLD: deeply negative raw hold but ex-jackpot near theo
SELECT
  m.run_id,
  'JACKPOT_DISTORTED_HOLD' AS flag,
  'info' AS severity,
  m.machine_id,
  m.bank_id,
  map(
    'actual_hold_pct',              CAST(m.actual_hold_pct AS BIGINT),
    'jackpot_adjusted_hold_pct',    CAST((m.coin_in_cents - m.coin_out_cents) / m.coin_in_cents * 100 AS BIGINT),
    'theoretical_hold_pct',         CAST(m.theoretical_hold_pct AS BIGINT),
    'jackpot_handpay_cents',        m.jackpot_handpay_cents
  ) AS context
FROM gold_machine_daily m
WHERE m.jackpot_handpay_cents > 0
  AND m.coin_in_cents > 0
  AND ABS(m.actual_hold_pct - m.theoretical_hold_pct) > 25
  AND ABS((m.coin_in_cents - m.coin_out_cents) / m.coin_in_cents * 100 - m.theoretical_hold_pct) < 12

UNION ALL
-- 3. METER_RECONCILIATION_GAP: summed BET coin-in vs latest poll meter
SELECT
  ev.run_id,
  'METER_RECONCILIATION_GAP' AS flag,
  'alert' AS severity,
  ev.machine_id,
  mp.bank_id,
  map(
    'event_coin_in_cents', ev.event_coin_in,
    'meter_coin_in_cents', mp.meter_coin_in,
    'gap_cents',           ABS(mp.meter_coin_in - ev.event_coin_in)
  ) AS context
FROM (
  SELECT run_id, machine_id, SUM(bet_cents) AS event_coin_in FROM silver_slot_spins GROUP BY run_id, machine_id
) ev
JOIN (
  SELECT run_id, machine_id, bank_id, max_by(coin_in_cents, sim_second) AS meter_coin_in
  FROM silver_meter_polls
  GROUP BY run_id, machine_id, bank_id
) mp USING (run_id, machine_id)
WHERE ABS(mp.meter_coin_in - ev.event_coin_in) > GREATEST(50, ev.event_coin_in * 0.02)

UNION ALL
-- 4. FAULT_RATE_SPIKE: bank fault minutes > 2× floor average
SELECT
  bank_fault.run_id,
  'FAULT_RATE_SPIKE' AS flag,
  'warning' AS severity,
  NULL AS machine_id,
  bank_fault.bank_id,
  map(
    'bank_fault_minutes',       CAST(bank_fault.fault_minutes AS BIGINT),
    'floor_avg_fault_minutes',  CAST(floor_avg.avg_fault_minutes AS BIGINT)
  ) AS context
FROM (
  SELECT
    run_id, bank_id,
    SUM(duration_seconds) / 60 AS fault_minutes
  FROM silver_machine_status s
  JOIN (
    SELECT entity_id AS machine_id, metadata:bank_id::string AS bank_id
    FROM bronze_floor_entities
    WHERE entity_type = 'machine'
  ) mb USING (machine_id)
  WHERE duration_seconds IS NOT NULL
  GROUP BY run_id, bank_id
) bank_fault
JOIN (
  SELECT run_id, AVG(fault_minutes) AS avg_fault_minutes FROM (
    SELECT run_id, bank_id, SUM(duration_seconds) / 60 AS fault_minutes
    FROM silver_machine_status s
    JOIN (
      SELECT entity_id AS machine_id, metadata:bank_id::string AS bank_id
      FROM bronze_floor_entities WHERE entity_type = 'machine'
    ) mb USING (machine_id)
    WHERE duration_seconds IS NOT NULL
    GROUP BY run_id, bank_id
  ) GROUP BY run_id
) floor_avg USING (run_id)
WHERE bank_fault.fault_minutes > 2 * floor_avg.avg_fault_minutes
  AND bank_fault.fault_minutes > 0.5

UNION ALL
-- 5. CONFIG_CHANGE_BASELINE_SHIFT: every CONFIG_CHANGE event
SELECT
  e.run_id,
  'CONFIG_CHANGE_BASELINE_SHIFT' AS flag,
  'info' AS severity,
  e.machine_id,
  mb.bank_id,
  map(
    'new_paytable_id',           e.payload:paytable_id::string,
    'new_theoretical_hold_pct',  e.payload:theoretical_hold_pct::string,
    'new_volatility',            e.payload:volatility::string
  ) AS context
FROM bronze_activity_events e
LEFT JOIN (
  SELECT entity_id AS machine_id, metadata:bank_id::string AS bank_id
  FROM bronze_floor_entities WHERE entity_type = 'machine'
) mb USING (machine_id)
WHERE e.event_type = 'CONFIG_CHANGE';
