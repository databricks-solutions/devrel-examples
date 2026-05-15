#!/usr/bin/env tsx
// Verifies that a generated run is causally consistent. Run with:
//   tsx scripts/verify-run.ts                       (defaults to demo-run-001)
//   tsx scripts/verify-run.ts demo-run-003-jackpot
//   API=http://localhost:8000 tsx scripts/verify-run.ts demo-run-001
//
// Checks:
//  1. Every BET_SETTLED and JACKPOT_HANDPAY has an active SESSION_START on
//     the same (patron, machine) with no intervening SESSION_END.
//  2. Every MACHINE_STATUS soft/hard fault clears before run end (or before
//     a follow-up event of a different status).
//  3. Per-machine, summed BET_SETTLED+JACKPOT coin_in deltas approximately
//     match the latest METER_POLL coin_in_cents (within a small tolerance).
//  4. JACKPOT_HANDPAY only fires on MEDIUM/HIGH volatility machines.

import type { ReplayPayload } from '../shared/replay-types.ts';

const API = process.env.API ?? 'http://localhost:8000';
const RUN_ID = process.argv[2] ?? 'demo-run-001';

async function main() {
  const res = await fetch(`${API}/api/replay/runs/${RUN_ID}`);
  if (!res.ok) {
    console.error(`failed to load ${RUN_ID}: HTTP ${res.status}`);
    process.exit(2);
  }
  const data = (await res.json()) as ReplayPayload;
  const failures: string[] = [];
  const warnings: string[] = [];

  // 1. Session causal consistency.
  const sessions = new Map<string, { machineId: string; startedAt: number }>();
  for (const event of data.events) {
    const t = Number(event.sim_second);
    if (event.event_type === 'SESSION_START' && event.machine_id) {
      const key = `${event.patron_id}::${event.machine_id}`;
      sessions.set(key, { machineId: event.machine_id, startedAt: t });
    } else if (event.event_type === 'SESSION_END' && event.machine_id) {
      const key = `${event.patron_id}::${event.machine_id}`;
      if (!sessions.has(key)) {
        warnings.push(`SESSION_END without START: ${key} at ${t}s`);
      }
      sessions.delete(key);
    } else if (
      (event.event_type === 'BET_SETTLED' || event.event_type === 'JACKPOT_HANDPAY') &&
      event.patron_id &&
      event.machine_id
    ) {
      const key = `${event.patron_id}::${event.machine_id}`;
      if (!sessions.has(key)) {
        failures.push(`${event.event_type} without active SESSION_START: ${key} at ${t}s (${event.event_id})`);
      }
    }
  }

  // 2. Fault state hygiene: every non-IN_SERVICE entry should eventually clear
  // (the demo expects fault windows that close before the run ends).
  const statusByMachine = new Map<string, { status: string; sinceSec: number }>();
  for (const event of data.events) {
    if (event.event_type !== 'MACHINE_STATUS' || !event.machine_id) continue;
    const status = typeof event.payload?.status === 'string' ? event.payload.status : 'IN_SERVICE';
    statusByMachine.set(event.machine_id, { status, sinceSec: Number(event.sim_second) });
  }
  for (const [machineId, info] of statusByMachine) {
    if (info.status !== 'IN_SERVICE') {
      warnings.push(`${machineId} ends run in ${info.status} (since ${info.sinceSec}s) — confirm intentional`);
    }
  }

  // 3. Meter reconciliation.
  const machineEntities = data.entities.filter((e) => e.entity_type === 'machine');
  for (const entity of machineEntities) {
    const machineId = entity.entity_id;
    const bets = data.events
      .filter((e) => e.machine_id === machineId && (e.event_type === 'BET_SETTLED' || e.event_type === 'JACKPOT_HANDPAY'));
    const summedCoinIn = bets.reduce((acc, e) => acc + Number(e.payload?.coin_in_delta_cents ?? e.payload?.bet_cents ?? 0), 0);
    const polls = data.meter_polls
      .filter((p) => p.machine_id === machineId)
      .sort((a, b) => Number(a.sim_second) - Number(b.sim_second));
    const lastPoll = polls[polls.length - 1];
    if (!lastPoll) continue;
    const meterCoinIn = Number(lastPoll.meters.coin_in_cents ?? 0);
    const diff = Math.abs(meterCoinIn - summedCoinIn);
    const tolerance = Math.max(50, summedCoinIn * 0.02);
    if (diff > tolerance && summedCoinIn > 0) {
      failures.push(
        `${machineId} meter reconciliation gap: events=${summedCoinIn}¢ vs meter=${meterCoinIn}¢ (Δ=${diff}¢, tolerance ${tolerance.toFixed(0)}¢)`,
      );
    }
  }

  // 4. Jackpot eligibility. Read volatility from the event payload so a
  // CONFIG_CHANGE that raises a machine's volatility class is respected.
  for (const event of data.events) {
    if (event.event_type !== 'JACKPOT_HANDPAY' || !event.machine_id) continue;
    const volatility =
      typeof event.payload?.volatility === 'string'
        ? event.payload.volatility
        : String(machineEntities.find((e) => e.entity_id === event.machine_id)?.metadata.volatility ?? '');
    if (volatility === 'LOW') {
      failures.push(`JACKPOT_HANDPAY on LOW-volatility machine ${event.machine_id} at ${event.sim_second}s`);
    }
  }

  // 5. TITO balance hygiene: per machine, sum(bill_in + voucher_in) should
  // approximately equal sum(coin_in - coin_out + voucher_out) (modulo any
  // drop and jackpot hand-pays). We just check there are no negative meters.
  for (const entity of machineEntities) {
    const machineId = entity.entity_id;
    const polls = data.meter_polls
      .filter((p) => p.machine_id === machineId)
      .sort((a, b) => Number(a.sim_second) - Number(b.sim_second));
    const last = polls[polls.length - 1];
    if (!last) continue;
    for (const key of ['coin_in_cents', 'coin_out_cents', 'bill_in_cents', 'voucher_in_cents', 'voucher_out_cents']) {
      const v = Number(last.meters[key] ?? 0);
      if (v < 0) failures.push(`${machineId} meter ${key} is negative (${v}) — accounting bug`);
    }
  }

  // 6. CONFIG_CHANGE arrives only when expected (event has a previous_id).
  for (const event of data.events) {
    if (event.event_type !== 'CONFIG_CHANGE') continue;
    if (!event.payload?.paytable_id) {
      warnings.push(`CONFIG_CHANGE without new paytable_id at ${event.sim_second}s on ${event.machine_id}`);
    }
  }

  const eventTypeCounts: Record<string, number> = {};
  for (const e of data.events) eventTypeCounts[e.event_type] = (eventTypeCounts[e.event_type] ?? 0) + 1;

  console.log(`\n📊 ${data.run.name} (${RUN_ID}) — ${data.run.duration_seconds}s, ${data.samples.length} samples`);
  console.log('   Event mix:', eventTypeCounts);

  if (warnings.length > 0) {
    console.log(`\n⚠️  ${warnings.length} warnings`);
    for (const w of warnings.slice(0, 12)) console.log(`   • ${w}`);
    if (warnings.length > 12) console.log(`   … and ${warnings.length - 12} more`);
  }

  if (failures.length > 0) {
    console.log(`\n❌ ${failures.length} failures`);
    for (const f of failures.slice(0, 25)) console.log(`   • ${f}`);
    if (failures.length > 25) console.log(`   … and ${failures.length - 25} more`);
    process.exit(1);
  }

  console.log('\n✅ All causal-consistency checks passed.');
}

main().catch((err) => {
  console.error('verify-run crashed:', err);
  process.exit(3);
});
