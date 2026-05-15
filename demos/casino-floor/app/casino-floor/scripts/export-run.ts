#!/usr/bin/env tsx
// Export a seeded run as JSONL files matching the silver/gold schemas in
// docs/analytics-tables.md. Lets us draft Genie queries against real-shaped
// data before any Delta plumbing exists.
//
//   tsx scripts/export-run.ts <runId> <outDir>
//   tsx scripts/export-run.ts demo-run-001 ../../data/exports/demo-run-001
//
// Reads from http://localhost:8000/api/replay/runs/:runId.

import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { ActivityEvent, MeterPoll, ReplayPayload } from '../shared/replay-types.ts';

const API = process.env.API ?? 'http://localhost:8000';
const RUN_ID = process.argv[2] ?? 'demo-run-001';
// Default to the demo's data/ dir so exports sit next to docs/ and manuals/.
// Script runs from app/casino-floor/, so go up two levels to demos/casino-floor/.
const OUT_DIR = process.argv[3] ?? `../../data/exports/${RUN_ID}`;

function num(v: unknown): number {
  return typeof v === 'number' ? v : Number(v ?? 0);
}

function str(v: unknown, fallback = ''): string {
  return typeof v === 'string' ? v : fallback;
}

function bool(v: unknown): boolean {
  return Boolean(v);
}

function ts(simSecond: number, runStart: string): string {
  return new Date(new Date(runStart).getTime() + simSecond * 1000).toISOString();
}

function writeJsonl<T>(dir: string, name: string, rows: T[]) {
  const path = join(dir, `${name}.jsonl`);
  const body = rows.map((r) => JSON.stringify(r)).join('\n') + (rows.length > 0 ? '\n' : '');
  writeFileSync(path, body);
  console.log(`  ${name}: ${rows.length} rows → ${path}`);
}

async function main() {
  const res = await fetch(`${API}/api/replay/runs/${RUN_ID}`);
  if (!res.ok) {
    console.error(`failed to load ${RUN_ID}: HTTP ${res.status}`);
    process.exit(2);
  }
  const data = (await res.json()) as ReplayPayload;
  mkdirSync(OUT_DIR, { recursive: true });
  console.log(`📦 ${data.run.name} (${RUN_ID}) → ${OUT_DIR}`);

  const machineEntities = data.entities.filter((e) => e.entity_type === 'machine');
  const machineToBank = new Map<string, string>();
  for (const e of machineEntities) {
    const meta = e.metadata as Record<string, unknown>;
    machineToBank.set(e.entity_id, str(meta.bank_id, 'bank-?'));
  }
  const runStart = String(data.run.starts_at);

  // ─── bronze_slot_events ────────────────────────────────────────────────
  const bronze = data.events.map((e) => ({
    event_id: e.event_id,
    run_id: RUN_ID,
    event_ts: ts(num(e.sim_second), runStart),
    sim_second: num(e.sim_second),
    event_type: e.event_type,
    entity_id: e.entity_id,
    patron_id: e.patron_id,
    machine_id: e.machine_id,
    bank_id: e.machine_id ? machineToBank.get(e.machine_id) ?? null : null,
    payload: e.payload,
  }));
  writeJsonl(OUT_DIR, 'bronze_slot_events', bronze);

  // ─── silver_slot_spins ─────────────────────────────────────────────────
  const silverSpins = data.events
    .filter((e) => e.event_type === 'BET_SETTLED' || e.event_type === 'JACKPOT_HANDPAY')
    .map((e) => ({
      event_id: e.event_id,
      run_id: RUN_ID,
      event_ts: ts(num(e.sim_second), runStart),
      sim_second: num(e.sim_second),
      machine_id: e.machine_id,
      bank_id: e.machine_id ? machineToBank.get(e.machine_id) ?? null : null,
      session_id: str(e.payload.session_id, ''),
      patron_id: e.patron_id,
      paytable_id: str(e.payload.paytable_id, ''),
      theoretical_hold_pct: num(e.payload.theoretical_hold_pct),
      volatility: str(e.payload.volatility, 'MEDIUM'),
      denomination_cents: num(e.payload.denomination_cents),
      bet_cents: num(e.payload.bet_cents),
      win_cents: num(e.payload.win_cents),
      jackpot_handpay_cents: num(e.payload.jackpot_handpay_cents),
      progressive_contribution_cents: num(e.payload.progressive_contribution_cents),
      progressive_pool_after_cents: num(e.payload.progressive_pool_after_cents),
      is_jackpot: e.event_type === 'JACKPOT_HANDPAY',
    }));
  writeJsonl(OUT_DIR, 'silver_slot_spins', silverSpins);

  // ─── silver_meter_polls ────────────────────────────────────────────────
  const sortedPolls = [...data.meter_polls].sort((a, b) => {
    const t = num(a.sim_second) - num(b.sim_second);
    return t !== 0 ? t : String(a.machine_id).localeCompare(String(b.machine_id));
  });
  const prevByMachine = new Map<string, MeterPoll>();
  const silverPolls = sortedPolls.map((p) => {
    const prev = prevByMachine.get(p.machine_id);
    const row = {
      run_id: RUN_ID,
      sim_second: num(p.sim_second),
      event_ts: ts(num(p.sim_second), runStart),
      machine_id: p.machine_id,
      bank_id: machineToBank.get(p.machine_id) ?? null,
      coin_in_cents: num(p.meters.coin_in_cents),
      coin_out_cents: num(p.meters.coin_out_cents),
      bill_in_cents: num(p.meters.bill_in_cents),
      voucher_in_cents: num(p.meters.voucher_in_cents),
      voucher_out_cents: num(p.meters.voucher_out_cents),
      jackpot_handpay_cents: num(p.meters.jackpot_handpay_cents),
      games_played: num(p.meters.games_played),
      coin_in_delta_cents: prev ? num(p.meters.coin_in_cents) - num(prev.meters.coin_in_cents) : num(p.meters.coin_in_cents),
      coin_out_delta_cents: prev ? num(p.meters.coin_out_cents) - num(prev.meters.coin_out_cents) : num(p.meters.coin_out_cents),
      jackpot_handpay_delta_cents: prev
        ? num(p.meters.jackpot_handpay_cents) - num(prev.meters.jackpot_handpay_cents)
        : num(p.meters.jackpot_handpay_cents),
      games_delta: prev ? num(p.meters.games_played) - num(prev.meters.games_played) : num(p.meters.games_played),
    };
    prevByMachine.set(p.machine_id, p);
    return row;
  });
  writeJsonl(OUT_DIR, 'silver_meter_polls', silverPolls);

  // ─── silver_machine_status ────────────────────────────────────────────
  const statusEvents = data.events.filter((e) => e.event_type === 'MACHINE_STATUS' && e.machine_id);
  const openStatus = new Map<string, ActivityEvent>();
  const machineStatusRows: Record<string, unknown>[] = [];
  for (const e of statusEvents) {
    const machineId = e.machine_id as string;
    const status = str(e.payload.status, 'IN_SERVICE');
    if (status === 'IN_SERVICE') {
      const opened = openStatus.get(machineId);
      if (opened) {
        machineStatusRows.push({
          run_id: RUN_ID,
          machine_id: machineId,
          bank_id: machineToBank.get(machineId) ?? null,
          entered_at_sim_second: num(opened.sim_second),
          cleared_at_sim_second: num(e.sim_second),
          duration_seconds: num(e.sim_second) - num(opened.sim_second),
          status: str(opened.payload.status, 'UNKNOWN'),
          previous_status: str(e.payload.previous_status, ''),
          expected_clear_at_sim_second: num(opened.payload.expected_clear_at),
        });
        openStatus.delete(machineId);
      }
    } else {
      openStatus.set(machineId, e);
    }
  }
  for (const [machineId, opened] of openStatus) {
    machineStatusRows.push({
      run_id: RUN_ID,
      machine_id: machineId,
      bank_id: machineToBank.get(machineId) ?? null,
      entered_at_sim_second: num(opened.sim_second),
      cleared_at_sim_second: null,
      duration_seconds: null,
      status: str(opened.payload.status, 'UNKNOWN'),
      previous_status: '',
      expected_clear_at_sim_second: num(opened.payload.expected_clear_at),
    });
  }
  writeJsonl(OUT_DIR, 'silver_machine_status', machineStatusRows);

  // ─── silver_patron_sessions ──────────────────────────────────────────
  const sessionsBySid = new Map<
    string,
    {
      session_id: string;
      machine_id: string | null;
      patron_id: string | null;
      started_at_sim_second: number;
      ended_at_sim_second: number | null;
      total_coin_in_cents: number;
      total_coin_out_cents: number;
      total_jackpot_handpay_cents: number;
      bet_count: number;
      cash_in_cents: number;
      ticket_out_cents: number;
      ended_reason: string;
      visited_bar_before: boolean;
      visited_bar_after: boolean;
    }
  >();
  // Track bar visits by patron to set visited_bar_before/after.
  const patronBarVisits = new Map<string, number[]>(); // sim_seconds
  for (const e of data.events) {
    if (e.event_type === 'BAR_VISIT' && e.patron_id) {
      const list = patronBarVisits.get(e.patron_id) ?? [];
      list.push(num(e.sim_second));
      patronBarVisits.set(e.patron_id, list);
    }
  }
  const sessionsOrder: string[] = [];
  for (const e of data.events) {
    const sid = str(e.payload.session_id, '');
    if (!sid) continue;
    if (e.event_type === 'SESSION_START') {
      sessionsOrder.push(sid);
      sessionsBySid.set(sid, {
        session_id: sid,
        machine_id: e.machine_id,
        patron_id: e.patron_id,
        started_at_sim_second: num(e.sim_second),
        ended_at_sim_second: null,
        total_coin_in_cents: 0,
        total_coin_out_cents: 0,
        total_jackpot_handpay_cents: 0,
        bet_count: 0,
        cash_in_cents: 0,
        ticket_out_cents: 0,
        ended_reason: '',
        visited_bar_before: false,
        visited_bar_after: false,
      });
    } else if (e.event_type === 'SESSION_END') {
      const s = sessionsBySid.get(sid);
      if (s) {
        s.ended_at_sim_second = num(e.sim_second);
        s.ended_reason = str(e.payload.reason, '');
        s.ticket_out_cents = num(e.payload.ticket_out_cents);
      }
    } else if (e.event_type === 'BET_SETTLED' || e.event_type === 'JACKPOT_HANDPAY') {
      const s = sessionsBySid.get(sid);
      if (s) {
        s.total_coin_in_cents += num(e.payload.coin_in_delta_cents);
        s.total_coin_out_cents += num(e.payload.coin_out_delta_cents);
        s.total_jackpot_handpay_cents += num(e.payload.jackpot_handpay_delta_cents);
        s.bet_count += 1;
      }
    } else if (e.event_type === 'CASH_IN') {
      const s = sessionsBySid.get(sid);
      if (s) s.cash_in_cents += num(e.payload.bill_in_delta_cents);
    } else if (e.event_type === 'TICKET_OUT') {
      const s = sessionsBySid.get(sid);
      if (s) s.ticket_out_cents += num(e.payload.voucher_out_delta_cents);
    }
  }
  const silverSessions = sessionsOrder.map((sid) => {
    const s = sessionsBySid.get(sid)!;
    const barVisits = (s.patron_id && patronBarVisits.get(s.patron_id)) || [];
    s.visited_bar_before = barVisits.some((t) => t < s.started_at_sim_second);
    s.visited_bar_after = s.ended_at_sim_second !== null && barVisits.some((t) => t > (s.ended_at_sim_second as number));
    const duration = s.ended_at_sim_second !== null ? s.ended_at_sim_second - s.started_at_sim_second : null;
    return {
      run_id: RUN_ID,
      session_id: s.session_id,
      machine_id: s.machine_id,
      bank_id: s.machine_id ? machineToBank.get(s.machine_id) ?? null : null,
      patron_id: s.patron_id,
      started_at_sim_second: s.started_at_sim_second,
      ended_at_sim_second: s.ended_at_sim_second,
      duration_seconds: duration,
      total_coin_in_cents: s.total_coin_in_cents,
      total_coin_out_cents: s.total_coin_out_cents,
      total_jackpot_handpay_cents: s.total_jackpot_handpay_cents,
      net_result_cents: s.total_coin_in_cents - s.total_coin_out_cents - s.total_jackpot_handpay_cents,
      bet_count: s.bet_count,
      cash_in_cents: s.cash_in_cents,
      ticket_out_cents: s.ticket_out_cents,
      ended_reason: s.ended_reason,
      visited_bar_before: bool(s.visited_bar_before),
      visited_bar_after: bool(s.visited_bar_after),
    };
  });
  writeJsonl(OUT_DIR, 'silver_patron_sessions', silverSessions);

  // ─── gold_machine_daily ──────────────────────────────────────────────
  const machineRollup = new Map<
    string,
    {
      coin_in: number;
      coin_out: number;
      jackpot: number;
      bets: number;
      games: number;
      sessions: Set<string>;
      theoreticalHoldWeighted: number;
      coinInForWeighting: number;
      lastVolatility: string;
    }
  >();
  for (const e of data.events) {
    if (!e.machine_id) continue;
    const row = machineRollup.get(e.machine_id) ?? {
      coin_in: 0,
      coin_out: 0,
      jackpot: 0,
      bets: 0,
      games: 0,
      sessions: new Set<string>(),
      theoreticalHoldWeighted: 0,
      coinInForWeighting: 0,
      lastVolatility: 'MEDIUM',
    };
    if (e.event_type === 'BET_SETTLED' || e.event_type === 'JACKPOT_HANDPAY') {
      const coinIn = num(e.payload.coin_in_delta_cents);
      row.coin_in += coinIn;
      row.coin_out += num(e.payload.coin_out_delta_cents);
      row.jackpot += num(e.payload.jackpot_handpay_delta_cents);
      row.bets += 1;
      row.games += 1;
      row.theoreticalHoldWeighted += coinIn * num(e.payload.theoretical_hold_pct);
      row.coinInForWeighting += coinIn;
      row.lastVolatility = str(e.payload.volatility, row.lastVolatility);
      const sid = str(e.payload.session_id, '');
      if (sid) row.sessions.add(sid);
    }
    machineRollup.set(e.machine_id, row);
  }
  const goldMachineDaily = machineEntities.map((m) => {
    const r = machineRollup.get(m.entity_id);
    const coinIn = r?.coin_in ?? 0;
    const coinOut = r?.coin_out ?? 0;
    const jackpot = r?.jackpot ?? 0;
    const actualWin = coinIn - coinOut - jackpot;
    const theoreticalHold =
      r && r.coinInForWeighting > 0 ? r.theoreticalHoldWeighted / r.coinInForWeighting : 0;
    return {
      run_id: RUN_ID,
      machine_id: m.entity_id,
      bank_id: machineToBank.get(m.entity_id) ?? null,
      volatility: r?.lastVolatility ?? str((m.metadata as Record<string, unknown>).volatility, 'MEDIUM'),
      coin_in_cents: coinIn,
      coin_out_cents: coinOut,
      jackpot_handpay_cents: jackpot,
      actual_win_cents: actualWin,
      actual_hold_pct: coinIn > 0 ? (actualWin / coinIn) * 100 : null,
      theoretical_hold_pct: theoreticalHold,
      theoretical_win_cents: Math.round((coinIn * theoreticalHold) / 100),
      hold_variance_bps:
        coinIn > 0 ? ((actualWin / coinIn) * 100 - theoreticalHold) * 100 : null,
      games_played: r?.games ?? 0,
      bet_count: r?.bets ?? 0,
      session_count: r?.sessions.size ?? 0,
    };
  });
  writeJsonl(OUT_DIR, 'gold_machine_daily', goldMachineDaily);

  // ─── gold_progressive_summary ────────────────────────────────────────
  const jackpotEvents = data.events.filter((e) => e.event_type === 'JACKPOT_HANDPAY');
  const totalContribution = silverSpins.reduce((acc, s) => acc + s.progressive_contribution_cents, 0);
  const eligibleCoinIn = silverSpins.reduce((acc, s) => acc + s.bet_cents, 0);
  const hitTimes = jackpotEvents.map((e) => num(e.sim_second));
  let meanGap: number | null = null;
  if (hitTimes.length >= 2) {
    const gaps = hitTimes.slice(1).map((t, i) => t - hitTimes[i]);
    meanGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
  }
  const lastPoolEvent = [...data.events]
    .reverse()
    .find((e) => typeof e.payload.progressive_pool_after_cents === 'number');
  const finalMeter = lastPoolEvent ? num(lastPoolEvent.payload.progressive_pool_after_cents) : 10_000;
  writeJsonl(OUT_DIR, 'gold_progressive_summary', [
    {
      run_id: RUN_ID,
      seed_cents: 10_000,
      final_meter_cents: finalMeter,
      hit_count: jackpotEvents.length,
      total_handpay_cents: jackpotEvents.reduce((acc, e) => acc + num(e.payload.jackpot_handpay_cents), 0),
      eligible_coin_in_cents: eligibleCoinIn,
      contribution_rate_pct: eligibleCoinIn > 0 ? (totalContribution / eligibleCoinIn) * 100 : 0,
      mean_seconds_between_hits: meanGap,
    },
  ]);

  // ─── gold_anomaly_candidates ──────────────────────────────────────────
  // Operator-relevant flags derived from the silver/gold rollups, matching
  // the six anomaly narratives in data/manuals/floor-narratives.md.
  const anomalies: Record<string, unknown>[] = [];
  const minMeaningfulCoinIn: Record<string, number> = { LOW: 2500, MEDIUM: 5000, HIGH: 10000 };

  for (const m of goldMachineDaily) {
    if (m.coin_in_cents === 0) continue;
    const minCoinIn = minMeaningfulCoinIn[m.volatility] ?? 5000;
    const adjHoldPct = m.coin_in_cents > 0 ? ((m.coin_in_cents - m.coin_out_cents) / m.coin_in_cents) * 100 : 0;
    const rawHoldPct = m.actual_hold_pct ?? 0;
    const theoPct = m.theoretical_hold_pct ?? 0;

    // LOW_COIN_IN_FALSE_POSITIVE: big gap at low volume.
    if (m.coin_in_cents < minCoinIn && Math.abs(rawHoldPct - theoPct) > 15) {
      anomalies.push({
        run_id: RUN_ID,
        flag: 'LOW_COIN_IN_FALSE_POSITIVE',
        severity: 'info',
        machine_id: m.machine_id,
        bank_id: m.bank_id,
        window_start_sim_second: 0,
        window_end_sim_second: Number(data.run.duration_seconds),
        context: {
          coin_in_cents: m.coin_in_cents,
          min_meaningful_coin_in_cents: minCoinIn,
          actual_hold_pct: rawHoldPct,
          theoretical_hold_pct: theoPct,
          gap_pp: rawHoldPct - theoPct,
        },
        evidence_event_ids: [],
      });
    }

    // JACKPOT_DISTORTED_HOLD: raw hold deeply negative but ex-jackpot hold near theo.
    if (
      m.jackpot_handpay_cents > 0 &&
      Math.abs(rawHoldPct - theoPct) > 25 &&
      Math.abs(adjHoldPct - theoPct) < 12
    ) {
      const jackpotEvtIds = jackpotEvents
        .filter((e) => e.machine_id === m.machine_id)
        .map((e) => e.event_id);
      anomalies.push({
        run_id: RUN_ID,
        flag: 'JACKPOT_DISTORTED_HOLD',
        severity: 'info',
        machine_id: m.machine_id,
        bank_id: m.bank_id,
        window_start_sim_second: 0,
        window_end_sim_second: Number(data.run.duration_seconds),
        context: {
          actual_hold_pct: rawHoldPct,
          jackpot_adjusted_hold_pct: adjHoldPct,
          theoretical_hold_pct: theoPct,
          jackpot_handpay_cents: m.jackpot_handpay_cents,
        },
        evidence_event_ids: jackpotEvtIds,
      });
    }
  }

  // METER_RECONCILIATION_GAP: per-machine summed BET coin-in vs last meter poll.
  const eventCoinInByMachine = new Map<string, number>();
  for (const s of silverSpins) {
    if (!s.machine_id) continue;
    eventCoinInByMachine.set(s.machine_id, (eventCoinInByMachine.get(s.machine_id) ?? 0) + s.bet_cents);
  }
  const latestPollByMachine = new Map<string, number>();
  for (const p of silverPolls) {
    if (!p.machine_id) continue;
    latestPollByMachine.set(p.machine_id, num(p.coin_in_cents));
  }
  for (const [machineId, meterCoinIn] of latestPollByMachine) {
    const eventCoinIn = eventCoinInByMachine.get(machineId) ?? 0;
    const gap = Math.abs(meterCoinIn - eventCoinIn);
    const tolerance = Math.max(50, eventCoinIn * 0.02);
    if (eventCoinIn > 0 && gap > tolerance) {
      anomalies.push({
        run_id: RUN_ID,
        flag: 'METER_RECONCILIATION_GAP',
        severity: 'alert',
        machine_id: machineId,
        bank_id: machineToBank.get(machineId) ?? null,
        window_start_sim_second: 0,
        window_end_sim_second: Number(data.run.duration_seconds),
        context: {
          event_coin_in_cents: eventCoinIn,
          meter_coin_in_cents: meterCoinIn,
          gap_cents: gap,
          tolerance_cents: tolerance,
        },
        evidence_event_ids: [],
      });
    }
  }

  // FAULT_RATE_SPIKE: bank-level fault minutes > floor average × 2.
  const bankFaultMinutes = new Map<string, number>();
  for (const row of machineStatusRows) {
    const bank = (row.bank_id as string) ?? 'bank-?';
    const duration = (row.duration_seconds as number | null) ?? 0;
    bankFaultMinutes.set(bank, (bankFaultMinutes.get(bank) ?? 0) + duration / 60);
  }
  if (bankFaultMinutes.size > 0) {
    const allFaultMinutes = Array.from(bankFaultMinutes.values());
    const floorAvg = allFaultMinutes.reduce((a, b) => a + b, 0) / allFaultMinutes.length;
    for (const [bank, minutes] of bankFaultMinutes) {
      if (minutes > floorAvg * 2 && minutes > 0.5) {
        anomalies.push({
          run_id: RUN_ID,
          flag: 'FAULT_RATE_SPIKE',
          severity: 'warning',
          machine_id: null,
          bank_id: bank,
          window_start_sim_second: 0,
          window_end_sim_second: Number(data.run.duration_seconds),
          context: {
            bank_fault_minutes: minutes,
            floor_avg_fault_minutes: floorAvg,
            ratio: minutes / Math.max(0.01, floorAvg),
          },
          evidence_event_ids: [],
        });
      }
    }
  }

  // CONFIG_CHANGE_BASELINE_SHIFT: any machine with a CONFIG_CHANGE in this run.
  const configChanges = data.events.filter((e) => e.event_type === 'CONFIG_CHANGE');
  for (const evt of configChanges) {
    anomalies.push({
      run_id: RUN_ID,
      flag: 'CONFIG_CHANGE_BASELINE_SHIFT',
      severity: 'info',
      machine_id: evt.machine_id,
      bank_id: evt.machine_id ? machineToBank.get(evt.machine_id) ?? null : null,
      window_start_sim_second: num(evt.sim_second),
      window_end_sim_second: Number(data.run.duration_seconds),
      context: {
        new_paytable_id: evt.payload.paytable_id,
        new_theoretical_hold_pct: evt.payload.theoretical_hold_pct,
        new_volatility: evt.payload.volatility,
        previous: evt.payload.previous,
      },
      evidence_event_ids: [evt.event_id],
    });
  }

  writeJsonl(OUT_DIR, 'gold_anomaly_candidates', anomalies);

  console.log(`✅ exported run ${RUN_ID} to ${OUT_DIR}`);
}

main().catch((err) => {
  console.error('export-run crashed:', err);
  process.exit(3);
});
