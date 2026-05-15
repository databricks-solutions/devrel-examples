import { useEffect, useMemo, useRef, useState } from 'react';
import { Application, Assets, Container, Graphics, Sprite, Text, Texture } from 'pixi.js';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Skeleton,
} from '@databricks/appkit-ui/react';

import type {
  ActivityEvent,
  FloorEntity,
  ReplayPayload,
  ReplayRun,
  ReplaySample,
} from '@shared/replay-types';

const TILE_SIZE = 34;
const FLOOR_WIDTH = 30;
const FLOOR_HEIGHT = 20;
const DEFAULT_RUN_ID = 'demo-run-001';
const CASINO_ASSET_BASE = '/assets/vendor/game-between-the-lines/casino';

// Curated jump-to timestamps per scenario so demo presenters can land on the
// narrative beat without scrubbing. Derived from the seeded events; if the
// underlying run changes, the timestamps may need to be re-tuned.
const SCENARIO_MOMENTS: Record<string, { label: string; simSecond: number }[]> = {
  'demo-run-001': [
    { label: 'Floor warming up', simSecond: 60 },
    { label: 'Mid-shift coin-in convergence', simSecond: 240 },
    { label: 'Bill validator fault — slot-008', simSecond: 300 },
    { label: 'Late-shift wind-down', simSecond: 540 },
  ],
  'demo-run-002-quiet': [
    { label: 'Quiet open', simSecond: 60 },
    { label: 'Low-volume hold drift', simSecond: 300 },
    { label: 'Sparse final stretch', simSecond: 540 },
  ],
  'demo-run-003-jackpot': [
    { label: 'First jackpot wave', simSecond: 120 },
    { label: 'Pool growth window', simSecond: 300 },
    { label: 'Second jackpot wave', simSecond: 480 },
  ],
  'demo-run-004-faults': [
    { label: 'Early soft faults', simSecond: 60 },
    { label: 'Bill validator outage', simSecond: 180 },
    { label: 'Traffic shifts to neighbors', simSecond: 300 },
    { label: 'Status backlog clears', simSecond: 480 },
  ],
  'demo-run-005-config-change': [
    { label: 'Pre-change baseline', simSecond: 180 },
    { label: 'Paytable swap — slot-005', simSecond: 240 },
    { label: 'New paytable settles in', simSecond: 420 },
    { label: 'Post-change comparison window', simSecond: 600 },
  ],
};

interface CasinoTextures {
  floorCarpetRed: Texture;
  floorCarpetBlue: Texture;
  floorCarpetPurple: Texture;
  wallTrimRed: Texture;
  plant: Texture;
  loungeTable: Texture;
  loungeChair: Texture;
  decorativeLamp: Texture;
  slotIdle: Texture;
  slotHot: Texture;
}

export function ReplayPage() {
  const [data, setData] = useState<ReplayPayload | null>(null);
  const [runs, setRuns] = useState<ReplayRun[]>([]);
  const [runId, setRunId] = useState<string>(DEFAULT_RUN_ID);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [time, setTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const startedAtRef = useRef<number | null>(null);
  const timeAtPlayRef = useRef(0);
  const currentTimeRef = useRef(0);

  useEffect(() => {
    fetch('/api/replay/runs')
      .then((res) => res.json() as Promise<ReplayRun[]>)
      .then((rows) => {
        setRuns(rows);
        if (rows.length > 0 && !rows.some((r) => r.run_id === runId)) {
          setRunId(rows[0].run_id);
        }
      })
      .catch(() => {
        /* ignored — single-run fallback below still works */
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setLoading(true);
    setSelectedId(null);
    setReplayTime(0);
    timeAtPlayRef.current = 0;
    startedAtRef.current = null;
    fetch(`/api/replay/runs/${runId}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load replay: ${res.statusText}`);
        return res.json() as Promise<ReplayPayload>;
      })
      .then((payload) => {
        setData(payload);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load replay'))
      .finally(() => setLoading(false));
  }, [runId]);

  const duration = Number(data?.run.duration_seconds ?? 120);

  const setReplayTime = (nextTime: number) => {
    const normalized = Number(nextTime.toFixed(3));
    currentTimeRef.current = normalized;
    setTime(normalized);
  };

  useEffect(() => {
    if (!isPlaying) {
      startedAtRef.current = null;
      timeAtPlayRef.current = currentTimeRef.current;
      return;
    }

    let frame = 0;
    const step = (now: number) => {
      if (startedAtRef.current === null) {
        startedAtRef.current = now;
      }
      const elapsed = ((now - startedAtRef.current) / 1000) * speed;
      const nextTime = (timeAtPlayRef.current + elapsed) % duration;
      setReplayTime(nextTime);
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [duration, isPlaying, speed]);

  const currentEvents = useMemo(() => {
    if (!data) return [];
    return data.events
      .filter((event) => Math.abs(Number(event.sim_second) - time) <= 4)
      .slice(-5);
  }, [data, time]);

  // Roll forward MACHINE_STATUS events to derive each machine's current status
  // at this replay time. Anything not IN_SERVICE earns a visible fault marker.
  const machineStatusAt = useMemo(() => {
    const status = new Map<string, string>();
    if (!data) return status;
    const sorted = data.events
      .filter((e) => e.event_type === 'MACHINE_STATUS' && e.machine_id && Number(e.sim_second) <= time)
      .sort((a, b) => Number(a.sim_second) - Number(b.sim_second));
    for (const evt of sorted) {
      const next = typeof evt.payload?.status === 'string' ? evt.payload.status : 'IN_SERVICE';
      status.set(evt.machine_id as string, next);
    }
    return status;
  }, [data, time]);

  // Per-machine snapshot at replay time: status + active session + recent
  // CONFIG_CHANGE flash. Powers the operator occupancy grid.
  const machineSnapshots = useMemo(() => {
    const snapshots = new Map<
      string,
      { status: string; occupied: boolean; configChangedSec: number | null; jackpotSec: number | null }
    >();
    if (!data) return snapshots;
    const machines = data.entities.filter((e) => e.entity_type === 'machine');
    for (const m of machines) {
      snapshots.set(m.entity_id, {
        status: machineStatusAt.get(m.entity_id) ?? 'IN_SERVICE',
        occupied: false,
        configChangedSec: null,
        jackpotSec: null,
      });
    }
    const openSessions = new Map<string, true>();
    for (const evt of data.events) {
      const t = Number(evt.sim_second);
      if (t > time) break;
      if (evt.event_type === 'SESSION_START' && evt.machine_id) openSessions.set(evt.machine_id, true);
      if (evt.event_type === 'SESSION_END' && evt.machine_id) openSessions.delete(evt.machine_id);
      if (evt.event_type === 'CONFIG_CHANGE' && evt.machine_id) {
        const snap = snapshots.get(evt.machine_id);
        if (snap) snap.configChangedSec = t;
      }
      if (evt.event_type === 'JACKPOT_HANDPAY' && evt.machine_id) {
        const snap = snapshots.get(evt.machine_id);
        if (snap) snap.jackpotSec = t;
      }
    }
    for (const machineId of openSessions.keys()) {
      const s = snapshots.get(machineId);
      if (s) s.occupied = true;
    }
    return snapshots;
  }, [data, time, machineStatusAt]);

  const bankKpis = useMemo(() => {
    if (!data) return [] as { bankId: string; coinIn: number; coinOut: number; jackpotPay: number; sessions: number; machines: number }[];
    const machines = data.entities.filter((e) => e.entity_type === 'machine');
    const machineToBank = new Map<string, string>();
    const banks = new Map<string, { coinIn: number; coinOut: number; jackpotPay: number; sessions: number; machines: number }>();
    for (const m of machines) {
      const bankRaw = m.metadata.bank_id;
      const bank = typeof bankRaw === 'string' ? bankRaw : 'bank-?';
      machineToBank.set(m.entity_id, bank);
      const existing = banks.get(bank) ?? { coinIn: 0, coinOut: 0, jackpotPay: 0, sessions: 0, machines: 0 };
      existing.machines += 1;
      banks.set(bank, existing);
    }
    const openSessions = new Map<string, string>();
    for (const evt of data.events) {
      const t = Number(evt.sim_second);
      if (t > time) break;
      const bank = evt.machine_id ? machineToBank.get(evt.machine_id) : undefined;
      if (!bank) continue;
      const entry = banks.get(bank);
      if (!entry) continue;
      if (evt.event_type === 'BET_SETTLED' || evt.event_type === 'JACKPOT_HANDPAY') {
        entry.coinIn += Number(evt.payload.coin_in_delta_cents ?? evt.payload.bet_cents ?? 0);
        entry.coinOut += Number(evt.payload.coin_out_delta_cents ?? evt.payload.win_cents ?? 0);
        entry.jackpotPay += Number(evt.payload.jackpot_handpay_delta_cents ?? evt.payload.jackpot_handpay_cents ?? 0);
      }
      if (evt.event_type === 'SESSION_START' && evt.machine_id) openSessions.set(evt.machine_id, bank);
      if (evt.event_type === 'SESSION_END' && evt.machine_id) openSessions.delete(evt.machine_id);
    }
    for (const bank of openSessions.values()) {
      const entry = banks.get(bank);
      if (entry) entry.sessions += 1;
    }
    return Array.from(banks.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([bankId, v]) => ({ bankId, ...v }));
  }, [data, time]);

  const faultedMachines = useMemo(() => {
    const out: { machineId: string; status: string; sinceSec: number | null }[] = [];
    for (const [machineId, status] of machineStatusAt) {
      if (status !== 'IN_SERVICE') {
        const lastTransition = data?.events
          .filter((e) => e.event_type === 'MACHINE_STATUS' && e.machine_id === machineId && Number(e.sim_second) <= time)
          .slice(-1)[0];
        out.push({ machineId, status, sinceSec: lastTransition ? Number(lastTransition.sim_second) : null });
      }
    }
    return out;
  }, [machineStatusAt, data, time]);

  // Floor-level KPIs at the current replay time.
  const floorKpis = useMemo(() => {
    if (!data) {
      return {
        coinInCents: 0,
        coinOutCents: 0,
        jackpotHandpayCents: 0,
        bets: 0,
        actualHoldPct: null as number | null,
        jackpotAdjustedHoldPct: null as number | null,
        activeSessions: 0,
        jackpotsToDate: 0,
        faultedCount: 0,
        occupancyPct: 0,
        archetypes: new Map<string, number>(),
        progressivePoolCents: null as number | null,
      };
    }
    let coinInCents = 0;
    let coinOutCents = 0;
    let jackpotHandpayCents = 0;
    let bets = 0;
    let jackpotsToDate = 0;
    let activeSessions = 0;
    let progressivePoolCents: number | null = null;
    const openSessions = new Map<string, true>();
    for (const evt of data.events) {
      const t = Number(evt.sim_second);
      if (t > time) break;
      if (evt.event_type === 'BET_SETTLED' || evt.event_type === 'JACKPOT_HANDPAY') {
        coinInCents += Number(evt.payload.coin_in_delta_cents ?? evt.payload.bet_cents ?? 0);
        coinOutCents += Number(evt.payload.coin_out_delta_cents ?? evt.payload.win_cents ?? 0);
        jackpotHandpayCents += Number(evt.payload.jackpot_handpay_delta_cents ?? evt.payload.jackpot_handpay_cents ?? 0);
        bets += 1;
        if (evt.event_type === 'JACKPOT_HANDPAY') jackpotsToDate += 1;
        if (typeof evt.payload.progressive_pool_after_cents === 'number') {
          progressivePoolCents = evt.payload.progressive_pool_after_cents;
        }
      }
      if (evt.event_type === 'SESSION_START' && evt.machine_id) openSessions.set(evt.machine_id, true);
      if (evt.event_type === 'SESSION_END' && evt.machine_id) openSessions.delete(evt.machine_id);
    }
    activeSessions = openSessions.size;

    // Archetype counts from current samples
    const archetypes = new Map<string, number>();
    const seenPatrons = new Set<string>();
    // Find sample closest to current time
    for (const sample of data.samples) {
      const t = Number(sample.sim_second);
      if (t > time + 0.6 || t < time - 0.6) continue;
      const id = sample.entity_id;
      if (seenPatrons.has(id)) continue;
      seenPatrons.add(id);
      const label = typeof sample.metadata.label === 'string' ? sample.metadata.label : 'Other';
      archetypes.set(label, (archetypes.get(label) ?? 0) + 1);
    }

    const totalMachines = data.entities.filter((e) => e.entity_type === 'machine').length;
    const occupancyPct = totalMachines > 0 ? (activeSessions / totalMachines) * 100 : 0;
    const actualWin = coinInCents - coinOutCents - jackpotHandpayCents;
    const actualHoldPct = coinInCents > 0 ? (actualWin / coinInCents) * 100 : null;
    // Ex-jackpot hold strips hand-pays, which dominate small-sample windows
    // and obscure the underlying machine economics.
    const jackpotAdjustedHoldPct: number | null = coinInCents > 0 ? ((coinInCents - coinOutCents) / coinInCents) * 100 : null;
    const faultedCount = faultedMachines.length;
    return {
      coinInCents,
      coinOutCents,
      jackpotHandpayCents,
      bets,
      actualHoldPct,
      jackpotAdjustedHoldPct,
      activeSessions,
      jackpotsToDate,
      faultedCount,
      occupancyPct,
      archetypes,
      progressivePoolCents,
    };
  }, [data, time, faultedMachines]);

  const selectedEntity = useMemo(() => {
    if (!data || !selectedId) return null;
    return data.entities.find((entity) => entity.entity_id === selectedId) ?? null;
  }, [data, selectedId]);

  const selectedPatron = useMemo(() => {
    if (!data || !selectedId) return null;
    const samples = data.samples.filter((sample) => sample.entity_id === selectedId);
    return interpolateSample(samples, time);
  }, [data, selectedId, time]);

  const selectedPatronInsight = useMemo(() => {
    if (!data || !selectedPatron) return null;
    const patronId = selectedPatron.entity_id;
    // Roll up this patron's event history up to current sim time.
    let totalBets = 0;
    let totalCoinIn = 0;
    let totalCoinOut = 0;
    let totalJackpotPay = 0;
    let totalCashIn = 0;
    let totalTicketOut = 0;
    let barVisits = 0;
    const sessions = new Map<
      string,
      {
        sessionId: string;
        machineId: string | null;
        startedAt: number;
        endedAt: number | null;
        endedReason: string;
        bets: number;
        coinIn: number;
        coinOut: number;
        jackpotPay: number;
      }
    >();
    for (const evt of data.events) {
      const t = Number(evt.sim_second);
      if (t > time) break;
      if (evt.patron_id !== patronId) continue;
      const sid = typeof evt.payload.session_id === 'string' ? evt.payload.session_id : null;
      switch (evt.event_type) {
        case 'SESSION_START':
          if (sid) {
            sessions.set(sid, {
              sessionId: sid,
              machineId: evt.machine_id,
              startedAt: t,
              endedAt: null,
              endedReason: '',
              bets: 0,
              coinIn: 0,
              coinOut: 0,
              jackpotPay: 0,
            });
          }
          break;
        case 'SESSION_END':
          if (sid) {
            const s = sessions.get(sid);
            if (s) {
              s.endedAt = t;
              s.endedReason =
                typeof evt.payload.reason === 'string' ? evt.payload.reason : '';
            }
          }
          break;
        case 'BET_SETTLED':
        case 'JACKPOT_HANDPAY': {
          const bet = Number(evt.payload.coin_in_delta_cents ?? evt.payload.bet_cents ?? 0);
          const win = Number(evt.payload.coin_out_delta_cents ?? evt.payload.win_cents ?? 0);
          const jp = Number(evt.payload.jackpot_handpay_delta_cents ?? evt.payload.jackpot_handpay_cents ?? 0);
          totalBets += 1;
          totalCoinIn += bet;
          totalCoinOut += win;
          totalJackpotPay += jp;
          if (sid) {
            const s = sessions.get(sid);
            if (s) {
              s.bets += 1;
              s.coinIn += bet;
              s.coinOut += win;
              s.jackpotPay += jp;
            }
          }
          break;
        }
        case 'CASH_IN':
          totalCashIn += Number(evt.payload.bill_in_delta_cents ?? 0);
          break;
        case 'TICKET_OUT':
          totalTicketOut += Number(evt.payload.voucher_out_delta_cents ?? 0);
          break;
        case 'BAR_VISIT':
          barVisits += 1;
          break;
      }
    }
    return {
      patron: selectedPatron,
      totalBets,
      totalCoinIn,
      totalCoinOut,
      totalJackpotPay,
      totalCashIn,
      totalTicketOut,
      barVisits,
      sessions: Array.from(sessions.values()).sort((a, b) => a.startedAt - b.startedAt),
    };
  }, [data, selectedPatron, time]);

  const selectedEvent = useMemo(() => {
    if (!data || !selectedId) return null;
    return data.events.find((event) => event.event_id === selectedId) ?? null;
  }, [data, selectedId]);

  const selectedMachineInsight = useMemo(() => {
    if (!data || !selectedId) return null;
    const entity = data.entities.find((e) => e.entity_id === selectedId);
    if (!entity || entity.entity_type !== 'machine') return null;

    const machineId = entity.entity_id;
    // Latest meter poll at or before current time
    const machinePolls = data.meter_polls
      .filter((p) => p.machine_id === machineId && Number(p.sim_second) <= time)
      .sort((a, b) => Number(a.sim_second) - Number(b.sim_second));
    const latestPoll = machinePolls[machinePolls.length - 1] ?? null;

    // Recent events for this machine in the visible window (last 30 simulated seconds)
    const recentEvents = data.events
      .filter((e) => e.machine_id === machineId && Number(e.sim_second) <= time && Number(e.sim_second) >= time - 30)
      .slice(-6);

    // Active session: most recent SESSION_START unmatched by SESSION_END before now
    const sessionEvents = data.events.filter(
      (e) =>
        e.machine_id === machineId &&
        (e.event_type === 'SESSION_START' || e.event_type === 'SESSION_END') &&
        Number(e.sim_second) <= time,
    );
    let activeSession: ActivityEvent | null = null;
    for (const evt of sessionEvents) {
      if (evt.event_type === 'SESSION_START') activeSession = evt;
      else activeSession = null;
    }

    // Compute coin-in / coin-out totals from all settled bets up to now
    const settledBets = data.events.filter(
      (e) =>
        e.machine_id === machineId &&
        (e.event_type === 'BET_SETTLED' || e.event_type === 'JACKPOT_HANDPAY') &&
        Number(e.sim_second) <= time,
    );
    let coinInCents = 0;
    let coinOutCents = 0;
    let jackpotHandpayCents = 0;
    let gamesPlayed = 0;
    for (const evt of settledBets) {
      coinInCents += Number(evt.payload.coin_in_delta_cents ?? evt.payload.bet_cents ?? 0);
      coinOutCents += Number(evt.payload.coin_out_delta_cents ?? evt.payload.win_cents ?? 0);
      jackpotHandpayCents += Number(evt.payload.jackpot_handpay_delta_cents ?? evt.payload.jackpot_handpay_cents ?? 0);
      gamesPlayed += 1;
    }
    const actualWin = coinInCents - coinOutCents - jackpotHandpayCents;
    const actualHoldPct = coinInCents > 0 ? (actualWin / coinInCents) * 100 : null;

    // Roll forward CONFIG_CHANGE events to get the currently-active paytable
    // and theoretical hold for this machine. Falls back to entity metadata.
    let currentPaytableId =
      typeof entity.metadata.paytable_id === 'string'
        ? entity.metadata.paytable_id
        : `PAR-${entity.entity_id.toUpperCase()}`;
    let currentVolatility =
      typeof entity.metadata.volatility === 'string' ? entity.metadata.volatility : 'MEDIUM';
    let currentTheoreticalHoldPct =
      Number(entity.metadata.theoretical_hold_pct ?? 0) ||
      (currentVolatility === 'LOW' ? 5.4 : currentVolatility === 'HIGH' ? 9.5 : 7.5);
    for (const evt of data.events) {
      if (evt.event_type !== 'CONFIG_CHANGE' || evt.machine_id !== machineId) continue;
      if (Number(evt.sim_second) > time) break;
      if (typeof evt.payload.paytable_id === 'string') currentPaytableId = evt.payload.paytable_id;
      if (typeof evt.payload.volatility === 'string') currentVolatility = evt.payload.volatility;
      if (typeof evt.payload.theoretical_hold_pct === 'number') currentTheoreticalHoldPct = evt.payload.theoretical_hold_pct;
    }

    return {
      entity,
      latestPoll,
      recentEvents,
      activeSession,
      coinInCents,
      coinOutCents,
      jackpotHandpayCents,
      gamesPlayed,
      actualHoldPct,
      theoreticalHoldPct: currentTheoreticalHoldPct,
      currentPaytableId,
      currentVolatility,
    };
  }, [data, selectedId, time]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-[560px] w-full" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Replay unavailable</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-destructive">{error ?? 'No replay data loaded.'}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="rounded-3xl border border-amber-500/20 bg-[radial-gradient(circle_at_20%_0%,rgba(245,158,11,0.18),transparent_32%),linear-gradient(135deg,#07040d,#111827_48%,#1b1026)] p-5 text-slate-100 shadow-2xl">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm uppercase tracking-[0.28em] text-amber-300">Casino Floor Replay</p>
          <h2 className="text-3xl font-bold text-white">{data.run.name}</h2>
          <p className="max-w-3xl text-sm text-slate-300">{data.run.description}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          {runs.length > 0 && (
            <label className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-400">
              Scenario
              <select
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
                className="h-9 rounded-md border border-amber-500/30 bg-slate-900 px-2 text-sm text-slate-100"
              >
                {runs.map((run) => (
                  <option key={run.run_id} value={run.run_id}>{run.name}</option>
                ))}
              </select>
            </label>
          )}
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="bg-amber-300 text-slate-950">
              Tick simulator
            </Badge>
            <Badge variant="outline" className="border-cyan-300/70 text-cyan-200">
              Lakebase backed
            </Badge>
          </div>
        </div>
      </section>

      <section className="mt-5 flex flex-wrap gap-2 rounded-2xl border border-amber-500/20 bg-slate-950/70 p-3 text-slate-100">
        <KpiTile label="Coin-in" value={`$${(floorKpis.coinInCents / 100).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`} sub={`${floorKpis.bets} bets`} />
        <KpiTile
          label="Actual hold"
          value={floorKpis.actualHoldPct === null ? '—' : `${floorKpis.actualHoldPct.toFixed(1)}%`}
          sub={floorKpis.coinInCents < 100_000 ? 'low volume — variance dominates' : 'incl. jackpots'}
          accent={floorKpis.actualHoldPct !== null && Math.abs(floorKpis.actualHoldPct - 7.5) > 4 ? 'amber' : 'neutral'}
        />
        <KpiTile
          label="Ex-jackpot hold"
          value={floorKpis.jackpotAdjustedHoldPct === null ? '—' : `${floorKpis.jackpotAdjustedHoldPct.toFixed(1)}%`}
          sub="vs 7.5% theo"
        />
        <KpiTile label="Active sessions" value={String(floorKpis.activeSessions)} sub={`${floorKpis.occupancyPct.toFixed(0)}% occupancy`} />
        <KpiTile
          label="Progressive pool"
          value={floorKpis.progressivePoolCents === null ? '—' : `$${(floorKpis.progressivePoolCents / 100).toFixed(2)}`}
          sub="resets on hit"
        />
        <KpiTile label="Jackpots" value={String(floorKpis.jackpotsToDate)} sub={`$${(floorKpis.jackpotHandpayCents / 100).toFixed(0)} hand pays`} />
        <KpiTile
          label="Faulted machines"
          value={String(floorKpis.faultedCount)}
          sub={floorKpis.faultedCount > 0 ? 'attendant needed' : 'all clear'}
          accent={floorKpis.faultedCount > 0 ? 'rose' : 'neutral'}
        />
      </section>

      {bankKpis.length > 0 && (
        <section className="mt-3 grid grid-cols-2 gap-2 rounded-2xl border border-slate-800 bg-slate-950/60 p-3 text-slate-100 sm:grid-cols-4">
          {bankKpis.map((bank) => {
            const hold = bank.coinIn > 0 ? ((bank.coinIn - bank.coinOut - bank.jackpotPay) / bank.coinIn) * 100 : null;
            return (
              <div key={bank.bankId} className="rounded-md border border-slate-800 bg-slate-900/70 px-3 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase tracking-wide text-slate-500">
                    {bank.bankId.replace('bank-', 'Bank ').toUpperCase()}
                  </span>
                  <span className="text-[10px] text-slate-500">{bank.machines} slots</span>
                </div>
                <div className="mt-0.5 font-mono text-lg leading-tight text-white">
                  ${(bank.coinIn / 100).toFixed(0)}
                </div>
                <div className="mt-0.5 grid grid-cols-2 gap-x-2 text-[10px] text-slate-400">
                  <span>Hold {hold === null ? '—' : `${hold.toFixed(0)}%`}</span>
                  <span>{bank.sessions} active</span>
                </div>
              </div>
            );
          })}
        </section>
      )}

      <section className="mt-3 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card className="overflow-hidden border-amber-500/20 bg-slate-950/95 text-slate-100 shadow-2xl">
          <CardHeader className="border-b border-amber-500/20 bg-slate-900/80">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="text-white">Floor Observer</CardTitle>
                <p className="text-xs text-slate-400">Live replay view with operational event highlights.</p>
              </div>
              <ReplayControls
                time={time}
                duration={duration}
                speed={speed}
                isPlaying={isPlaying}
                onPlayChange={(next) => {
                  timeAtPlayRef.current = currentTimeRef.current;
                  startedAtRef.current = null;
                  setIsPlaying(next);
                }}
                onSpeedChange={(next) => {
                  timeAtPlayRef.current = currentTimeRef.current;
                  startedAtRef.current = null;
                  setSpeed(next);
                }}
                onSeek={(next) => {
                  startedAtRef.current = null;
                  timeAtPlayRef.current = next;
                  setReplayTime(next);
                }}
              />
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <FloorCanvas
              data={data}
              time={time}
              selectedId={selectedId}
              events={currentEvents}
              eventIds={currentEvents.flatMap((event) => [event.machine_id, event.patron_id]).filter(Boolean) as string[]}
              machineStatus={machineStatusAt}
              onSelect={setSelectedId}
            />
            {SCENARIO_MOMENTS[runId] && (
              <div className="flex flex-wrap items-center gap-1.5 border-t border-amber-500/15 bg-slate-950/80 px-4 py-2 text-xs">
                <span className="mr-1 text-[10px] uppercase tracking-wide text-slate-500">Jump to</span>
                {SCENARIO_MOMENTS[runId].map((moment) => (
                  <button
                    key={`${runId}-${moment.simSecond}`}
                    type="button"
                    onClick={() => {
                      startedAtRef.current = null;
                      timeAtPlayRef.current = moment.simSecond;
                      setReplayTime(moment.simSecond);
                    }}
                    className="rounded-full border border-slate-700 bg-slate-900/70 px-2.5 py-1 text-[11px] text-slate-200 transition-colors hover:border-amber-400/70 hover:bg-amber-500/20 hover:text-amber-100"
                  >
                    {moment.label} <span className="text-slate-500">· {moment.simSecond}s</span>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <aside className="space-y-4">
          <Card className="border-amber-500/20 bg-slate-950/90 text-slate-100">
            <CardHeader>
              <CardTitle>Inspector</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {!selectedId && <p className="text-slate-400">Select a machine, patron, or event.</p>}
              {selectedMachineInsight && (
                <MachineParCard insight={selectedMachineInsight} />
              )}
              {selectedEntity && !selectedMachineInsight && (
                <InspectorBlock
                  title={selectedEntity.label}
                  rows={[
                    ['Type', selectedEntity.entity_type],
                    ['ID', selectedEntity.entity_id],
                    ['Position', `${selectedEntity.x}, ${selectedEntity.y}`],
                    ['Metadata', JSON.stringify(selectedEntity.metadata)],
                  ]}
                />
              )}
              {selectedPatronInsight && (
                <PatronCard insight={selectedPatronInsight} />
              )}
              {selectedEvent && (
                <InspectorBlock
                  title={selectedEvent.title}
                  rows={[
                    ['Type', selectedEvent.event_type],
                    ['Time', `${selectedEvent.sim_second}s`],
                    ['Machine', selectedEvent.machine_id ?? 'n/a'],
                    ['Patron', selectedEvent.patron_id ?? 'n/a'],
                    ['Details', selectedEvent.description],
                  ]}
                />
              )}
            </CardContent>
          </Card>

          <Card className="border-amber-500/20 bg-slate-950/90 text-slate-100">
            <CardHeader>
              <CardTitle>Nearby Events</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {currentEvents.length === 0 && (
                <p className="text-sm text-slate-400">No events near this replay time.</p>
              )}
              {currentEvents.map((event) => (
                <button
                  key={event.event_id}
                  type="button"
                  onClick={() => setSelectedId(event.event_id)}
                  className="w-full rounded-md border border-slate-800 bg-slate-900/70 p-3 text-left text-sm transition-colors hover:border-amber-400/70 hover:bg-slate-800"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{event.title}</span>
                    <Badge variant="outline">{Number(event.sim_second).toFixed(0)}s</Badge>
                  </div>
                  <p className="mt-1 text-xs text-slate-400">{event.description}</p>
                </button>
              ))}
            </CardContent>
          </Card>

          <Card className="border-amber-500/20 bg-slate-950/90 text-slate-100">
            <CardHeader>
              <CardTitle className="text-sm">Machine grid</CardTitle>
            </CardHeader>
            <CardContent>
              <MachineOccupancyGrid
                entities={data.entities}
                snapshots={machineSnapshots}
                time={time}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
              <p className="mt-2 text-[10px] text-slate-500">
                green = in session · gray = idle · amber = soft fault · rose = hard fault · purple = config change (recent) · cyan = jackpot (recent)
              </p>
            </CardContent>
          </Card>

          {floorKpis.archetypes.size > 0 && (
            <Card className="border-amber-500/20 bg-slate-950/90 text-slate-100">
              <CardHeader>
                <CardTitle className="text-sm">Patrons on the floor</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5 text-sm">
                {Array.from(floorKpis.archetypes.entries())
                  .sort((a, b) => b[1] - a[1])
                  .map(([label, count]) => (
                    <div key={label} className="flex items-center justify-between">
                      <span className="text-slate-300">{label}</span>
                      <span className="font-mono text-slate-100">{count}</span>
                    </div>
                  ))}
                <div className="mt-2 border-t border-slate-800 pt-2 flex items-center justify-between text-xs text-slate-400">
                  <span>Total</span>
                  <span className="font-mono">
                    {Array.from(floorKpis.archetypes.values()).reduce((a, b) => a + b, 0)}
                  </span>
                </div>
              </CardContent>
            </Card>
          )}

          {faultedMachines.length > 0 && (
            <Card className="border-rose-400/30 bg-slate-950/90 text-slate-100">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-rose-200">
                  <span className="inline-block h-2 w-2 rounded-full bg-rose-400 shadow-[0_0_10px_#fb7185]" />
                  Floor status alerts
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {faultedMachines.map((fault) => (
                  <button
                    key={fault.machineId}
                    type="button"
                    onClick={() => setSelectedId(fault.machineId)}
                    className="flex w-full items-center justify-between rounded-md border border-slate-800 bg-slate-900/70 px-3 py-2 text-left transition-colors hover:border-rose-400/60 hover:bg-slate-800"
                  >
                    <span className="font-medium">{fault.machineId}</span>
                    <span className="flex items-center gap-2">
                      <Badge
                        variant="outline"
                        className={
                          fault.status === 'BILL_VALIDATOR_FAULT' ||
                          fault.status === 'OUT_OF_SERVICE' ||
                          fault.status === 'DOOR_OPEN'
                            ? 'border-rose-400/60 text-rose-300'
                            : 'border-amber-300/60 text-amber-300'
                        }
                      >
                        {fault.status.replace(/_/g, ' ').toLowerCase()}
                      </Badge>
                      {fault.sinceSec !== null && (
                        <span className="text-[10px] text-slate-500">since {fault.sinceSec.toFixed(0)}s</span>
                      )}
                    </span>
                  </button>
                ))}
              </CardContent>
            </Card>
          )}
        </aside>
      </section>
    </div>
  );
}

function ReplayControls({
  time,
  duration,
  speed,
  isPlaying,
  onPlayChange,
  onSpeedChange,
  onSeek,
}: {
  time: number;
  duration: number;
  speed: number;
  isPlaying: boolean;
  onPlayChange: (next: boolean) => void;
  onSpeedChange: (next: number) => void;
  onSeek: (next: number) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-full border border-slate-700 bg-slate-950/80 px-3 py-2 shadow-lg">
      <Button size="sm" className="bg-amber-300 text-slate-950 hover:bg-amber-200" onClick={() => onPlayChange(!isPlaying)}>
        {isPlaying ? 'Pause' : 'Play'}
      </Button>
      <select
        value={speed}
        onChange={(event) => onSpeedChange(Number(event.target.value))}
        className="h-9 rounded-md border border-slate-700 bg-slate-900 px-2 text-sm text-slate-100"
      >
        <option value={0.5}>0.5x</option>
        <option value={1}>1x</option>
        <option value={2}>2x</option>
        <option value={4}>4x</option>
      </select>
      <input
        type="range"
        min={0}
        max={duration}
        step={1}
        value={time}
        onChange={(event) => onSeek(Number(event.target.value))}
        className="w-56 accent-amber-300"
      />
      <span className="w-20 text-right font-mono text-sm text-slate-300">
        {time.toFixed(0)}s / {duration}s
      </span>
    </div>
  );
}

function KpiTile({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: 'rose' | 'amber' | 'neutral';
}) {
  const valueClass =
    accent === 'rose'
      ? 'text-rose-300'
      : accent === 'amber'
        ? 'text-amber-300'
        : 'text-white';
  return (
    <div className="flex min-w-[120px] flex-1 flex-col gap-0.5 rounded-md border border-slate-800 bg-slate-900/70 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`font-mono text-xl font-semibold leading-tight ${valueClass}`}>{value}</div>
      {sub && <div className="text-[10px] text-slate-500">{sub}</div>}
    </div>
  );
}

function InspectorBlock({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div>
      <h3 className="font-semibold">{title}</h3>
      <dl className="mt-2 space-y-2">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
            <dd className="break-words font-mono text-xs text-slate-200">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

interface MachineInsight {
  entity: FloorEntity;
  latestPoll: { sim_second: number | string; meters: Record<string, number | string> } | null;
  recentEvents: ActivityEvent[];
  activeSession: ActivityEvent | null;
  currentPaytableId: string;
  currentVolatility: string;
  coinInCents: number;
  coinOutCents: number;
  jackpotHandpayCents: number;
  gamesPlayed: number;
  actualHoldPct: number | null;
  theoreticalHoldPct: number;
}

function MachineParCard({ insight }: { insight: MachineInsight }) {
  const meta = insight.entity.metadata;
  const theme = typeof meta.theme === 'string' ? meta.theme : '—';
  const bank = typeof meta.bank_id === 'string' ? meta.bank_id : '—';
  const denom = typeof meta.denomination_cents === 'number' ? meta.denomination_cents : 25;
  const volatility = insight.currentVolatility;
  const paytableId = insight.currentPaytableId;
  const swappedFromOriginal =
    (typeof meta.volatility === 'string' && meta.volatility !== volatility) ||
    (typeof meta.paytable_id === 'string' && meta.paytable_id !== paytableId);
  const holdGap =
    insight.actualHoldPct !== null
      ? insight.actualHoldPct - insight.theoreticalHoldPct
      : null;
  const occupancy = insight.activeSession?.patron_id ?? null;

  return (
    <div className="space-y-3">
      <div className="rounded-md border border-amber-500/30 bg-gradient-to-b from-amber-900/30 to-slate-900/60 p-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-semibold text-white">{insight.entity.label}</h3>
          <Badge variant="outline" className="border-amber-300/60 text-amber-200">
            {bank.toUpperCase().replace('BANK-', 'BANK ')}
          </Badge>
        </div>
        <p className="mt-0.5 text-xs text-slate-400">
          {theme} · {paytableId}
          {swappedFromOriginal && (
            <span className="ml-2 inline-flex items-center rounded-sm bg-purple-500/30 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-purple-100">
              config changed
            </span>
          )}
        </p>
        <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
          <div>
            <div className="uppercase tracking-wide text-slate-500">Denom</div>
            <div className="font-mono text-slate-200">${(denom / 100).toFixed(2)}</div>
          </div>
          <div>
            <div className="uppercase tracking-wide text-slate-500">Volatility</div>
            <div className="font-mono text-slate-200">{volatility}</div>
          </div>
          <div>
            <div className="uppercase tracking-wide text-slate-500">Theo Hold</div>
            <div className="font-mono text-slate-200">{insight.theoreticalHoldPct.toFixed(1)}%</div>
          </div>
          <div>
            <div className="uppercase tracking-wide text-slate-500">Actual Hold</div>
            <div className={`font-mono ${holdGap !== null && Math.abs(holdGap) > 3 ? 'text-amber-300' : 'text-slate-200'}`}>
              {insight.actualHoldPct === null ? '—' : `${insight.actualHoldPct.toFixed(1)}%`}
              {holdGap !== null && insight.gamesPlayed >= 8 && (
                <span className="ml-1 text-[10px] text-slate-500">({holdGap >= 0 ? '+' : ''}{holdGap.toFixed(1)})</span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-md border border-slate-800 bg-slate-900/50 p-3 text-xs">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="font-semibold text-slate-300">Live meters</span>
          <span className="text-[10px] uppercase tracking-wide text-slate-500">
            {insight.latestPoll ? `polled ${Number(insight.latestPoll.sim_second).toFixed(0)}s` : 'no poll yet'}
          </span>
        </div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
          <Meter label="Games" value={String(insight.gamesPlayed)} />
          <Meter label="Coin-in" value={`$${(insight.coinInCents / 100).toFixed(2)}`} />
          <Meter label="Coin-out" value={`$${(insight.coinOutCents / 100).toFixed(2)}`} />
          <Meter label="Jackpot pay" value={`$${(insight.jackpotHandpayCents / 100).toFixed(2)}`} />
        </dl>
      </div>

      <div className="rounded-md border border-slate-800 bg-slate-900/50 p-3 text-xs">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="font-semibold text-slate-300">Occupancy</span>
          {occupancy ? (
            <Badge variant="outline" className="border-cyan-400/50 text-cyan-300">in session</Badge>
          ) : (
            <Badge variant="outline" className="border-slate-600 text-slate-500">idle</Badge>
          )}
        </div>
        <p className="font-mono text-slate-200">{occupancy ?? 'no active session'}</p>
      </div>

      {insight.recentEvents.length > 0 && (
        <div className="rounded-md border border-slate-800 bg-slate-900/50 p-3 text-xs">
          <div className="mb-1.5 font-semibold text-slate-300">Recent activity</div>
          <ul className="space-y-1.5">
            {insight.recentEvents.map((evt) => (
              <li key={evt.event_id} className="flex justify-between gap-2">
                <span className="text-slate-300">{evt.event_type.replace(/_/g, ' ').toLowerCase()}</span>
                <span className="font-mono text-slate-500">{Number(evt.sim_second).toFixed(0)}s</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function MachineOccupancyGrid({
  entities,
  snapshots,
  time,
  selectedId,
  onSelect,
}: {
  entities: FloorEntity[];
  snapshots: Map<string, { status: string; occupied: boolean; configChangedSec: number | null; jackpotSec: number | null }>;
  time: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const machines = useMemo(
    () => entities.filter((e) => e.entity_type === 'machine').sort((a, b) => a.entity_id.localeCompare(b.entity_id)),
    [entities],
  );
  // Group by bank for the 4×5 layout
  const byBank = useMemo(() => {
    const groups = new Map<string, FloorEntity[]>();
    for (const m of machines) {
      const rawBank = m.metadata.bank_id;
      const bank = typeof rawBank === 'string' ? rawBank : 'bank-?';
      const list = groups.get(bank) ?? [];
      list.push(m);
      groups.set(bank, list);
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [machines]);

  return (
    <div className="space-y-1.5">
      {byBank.map(([bank, group]) => (
        <div key={bank} className="flex items-center gap-1.5">
          <div className="w-10 text-[10px] uppercase tracking-wide text-slate-500">
            {bank.replace('bank-', '')}
          </div>
          <div className="flex flex-1 gap-1">
            {group.map((m) => {
              const snap = snapshots.get(m.entity_id);
              const isSelected = selectedId === m.entity_id;
              const isConfigRecent = snap?.configChangedSec !== null && snap?.configChangedSec !== undefined && time - snap.configChangedSec < 6;
              const isJackpotRecent = snap?.jackpotSec !== null && snap?.jackpotSec !== undefined && time - snap.jackpotSec < 5;
              const status = snap?.status ?? 'IN_SERVICE';
              const hardFault =
                status === 'BILL_VALIDATOR_FAULT' || status === 'OUT_OF_SERVICE' || status === 'DOOR_OPEN';
              const softFault = status === 'SOFT_FAULT';
              let cellClasses =
                'flex h-9 flex-1 items-center justify-center rounded-md border text-[10px] font-mono transition-colors cursor-pointer';
              if (isJackpotRecent) cellClasses += ' border-cyan-300 bg-cyan-400/30 text-cyan-100';
              else if (isConfigRecent) cellClasses += ' border-purple-300 bg-purple-400/25 text-purple-100';
              else if (hardFault) cellClasses += ' border-rose-400 bg-rose-500/30 text-rose-100';
              else if (softFault) cellClasses += ' border-amber-400 bg-amber-500/25 text-amber-100';
              else if (snap?.occupied) cellClasses += ' border-emerald-400/60 bg-emerald-500/25 text-emerald-100';
              else cellClasses += ' border-slate-700 bg-slate-800/50 text-slate-400';
              if (isSelected) cellClasses += ' ring-2 ring-white';
              return (
                <button
                  key={m.entity_id}
                  type="button"
                  onClick={() => onSelect(m.entity_id)}
                  className={cellClasses}
                  title={`${m.entity_id} · ${status}${snap?.occupied ? ' · in session' : ''}`}
                >
                  {m.entity_id.replace('slot-', '')}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

interface PatronInsight {
  patron: ReplaySample;
  totalBets: number;
  totalCoinIn: number;
  totalCoinOut: number;
  totalJackpotPay: number;
  totalCashIn: number;
  totalTicketOut: number;
  barVisits: number;
  sessions: {
    sessionId: string;
    machineId: string | null;
    startedAt: number;
    endedAt: number | null;
    endedReason: string;
    bets: number;
    coinIn: number;
    coinOut: number;
    jackpotPay: number;
  }[];
}

function PatronCard({ insight }: { insight: PatronInsight }) {
  const p = insight.patron;
  const meta = p.metadata;
  const label = typeof meta.label === 'string' ? meta.label : 'Casual Player';
  const behavior = typeof meta.behavior === 'string' ? meta.behavior : 'casual';
  const bankrollCents = Number(meta.bankroll_cents ?? 0);
  const walletCents = Number(meta.wallet_cents ?? 0);
  const colorValue = typeof meta.color === 'string' ? meta.color : '#40d1f5';
  const netResult = insight.totalCoinIn - insight.totalCoinOut - insight.totalJackpotPay;
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-cyan-400/30 bg-gradient-to-b from-cyan-900/30 to-slate-900/60 p-3">
        <div className="flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-full" style={{ backgroundColor: colorValue, boxShadow: `0 0 8px ${colorValue}` }} />
          <h3 className="flex-1 font-semibold text-white">{label}</h3>
          <Badge variant="outline" className="border-cyan-300/60 text-cyan-200 capitalize">
            {behavior.replace(/_/g, ' ')}
          </Badge>
        </div>
        <p className="mt-0.5 font-mono text-xs text-slate-400">{p.entity_id}</p>
        <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
          <div>
            <div className="uppercase tracking-wide text-slate-500">Activity</div>
            <div className="font-mono text-slate-200">{p.activity}</div>
          </div>
          <div>
            <div className="uppercase tracking-wide text-slate-500">Target</div>
            <div className="font-mono text-slate-200">{p.target_id ?? '—'}</div>
          </div>
          <div>
            <div className="uppercase tracking-wide text-slate-500">Wallet</div>
            <div className="font-mono text-slate-200">${(walletCents / 100).toFixed(2)}</div>
          </div>
          <div>
            <div className="uppercase tracking-wide text-slate-500">Bankroll</div>
            <div className="font-mono text-slate-200">${(bankrollCents / 100).toFixed(2)}</div>
          </div>
        </div>
      </div>

      <div className="rounded-md border border-slate-800 bg-slate-900/50 p-3 text-xs">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="font-semibold text-slate-300">Activity to date</span>
          <span
            className={`font-mono ${netResult < 0 ? 'text-emerald-300' : netResult > 0 ? 'text-rose-300' : 'text-slate-300'}`}
          >
            net {netResult < 0 ? '+' : netResult > 0 ? '-' : ''}${(Math.abs(netResult) / 100).toFixed(2)}
          </span>
        </div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
          <Meter label="Bets" value={String(insight.totalBets)} />
          <Meter label="Bar visits" value={String(insight.barVisits)} />
          <Meter label="Coin-in" value={`$${(insight.totalCoinIn / 100).toFixed(2)}`} />
          <Meter label="Coin-out" value={`$${(insight.totalCoinOut / 100).toFixed(2)}`} />
          <Meter label="Cash-in" value={`$${(insight.totalCashIn / 100).toFixed(2)}`} />
          <Meter label="Tickets out" value={`$${(insight.totalTicketOut / 100).toFixed(2)}`} />
        </dl>
        <p className="mt-1.5 text-[10px] text-slate-500">
          Net is from the patron&apos;s perspective — positive means they walked away ahead.
        </p>
      </div>

      {insight.sessions.length > 0 && (
        <div className="rounded-md border border-slate-800 bg-slate-900/50 p-3 text-xs">
          <div className="mb-1.5 font-semibold text-slate-300">
            Sessions ({insight.sessions.length})
          </div>
          <ul className="space-y-1.5">
            {insight.sessions.map((s) => {
              const sessionNet = s.coinIn - s.coinOut - s.jackpotPay;
              const duration = s.endedAt !== null ? s.endedAt - s.startedAt : null;
              return (
                <li key={s.sessionId} className="rounded border border-slate-800/70 bg-slate-950/40 px-2 py-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-slate-200">{s.machineId ?? '—'}</span>
                    <span className="text-slate-500">
                      {duration === null ? `${s.startedAt.toFixed(0)}s · open` : `${duration.toFixed(0)}s`}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-center justify-between gap-2 text-[11px]">
                    <span className="text-slate-400">
                      {s.bets} bets · ${(s.coinIn / 100).toFixed(2)} in
                    </span>
                    <span className={sessionNet < 0 ? 'text-emerald-300' : sessionNet > 0 ? 'text-rose-300' : 'text-slate-400'}>
                      {sessionNet < 0 ? '+' : sessionNet > 0 ? '-' : ''}${(Math.abs(sessionNet) / 100).toFixed(2)}
                    </span>
                  </div>
                  {s.endedReason && (
                    <div className="text-[10px] uppercase tracking-wide text-slate-500">
                      {s.endedReason.replace(/_/g, ' ')}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function Meter({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="font-mono text-slate-200">{value}</dd>
    </div>
  );
}

function FloorCanvas({
  data,
  time,
  selectedId,
  events,
  eventIds,
  machineStatus,
  onSelect,
}: {
  data: ReplayPayload;
  time: number;
  selectedId: string | null;
  events: ActivityEvent[];
  eventIds: string[];
  machineStatus: Map<string, string>;
  onSelect: (id: string) => void;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const appRef = useRef<Application | null>(null);
  const floorLayerRef = useRef<Container | null>(null);
  const entityLayerRef = useRef<Container | null>(null);
  const entityHitLayerRef = useRef<Container | null>(null);
  const patronLayerRef = useRef<Container | null>(null);
  const texturesRef = useRef<CasinoTextures | null>(null);
  const patronGraphicsRef = useRef<Map<string, Graphics>>(new Map());
  const onSelectRef = useRef(onSelect);
  // Keep the ref in sync with the latest onSelect so the stable click overlay
  // dispatches to the current React state setter. Done in an effect so React
  // doesn't complain about ref mutation during render.
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);
  const [pixiReady, setPixiReady] = useState(false);

  // Index samples by patron once per data load. Avoids O(N) filter per patron
  // per frame which previously made 100+ patrons stutter / crash the tab.
  const samplesByPatron = useMemo(() => {
    const map = new Map<string, ReplaySample[]>();
    for (const sample of data.samples) {
      let list = map.get(sample.entity_id);
      if (!list) {
        list = [];
        map.set(sample.entity_id, list);
      }
      list.push(sample);
    }
    for (const list of map.values()) {
      list.sort((a, b) => Number(a.sim_second) - Number(b.sim_second));
    }
    return map;
  }, [data.samples]);

  useEffect(() => {
    let cancelled = false;
    let initialized = false;
    const patronRegistry = patronGraphicsRef.current;
    const app = new Application();
    appRef.current = app;

    void Promise.all([
      loadCasinoTextures(),
      app.init({
        background: '#111827',
        antialias: false,
        width: FLOOR_WIDTH * TILE_SIZE,
        height: FLOOR_HEIGHT * TILE_SIZE,
      }),
    ])
      .then(([textures]) => {
        initialized = true;
        if (cancelled || !hostRef.current) {
          app.destroy(true);
          return;
        }
        texturesRef.current = textures;
        const floorLayer = new Container();
        const entityLayer = new Container();
        const patronLayer = new Container();
        const entityHitLayer = new Container();
        floorLayerRef.current = floorLayer;
        entityLayerRef.current = entityLayer;
        patronLayerRef.current = patronLayer;
        entityHitLayerRef.current = entityHitLayer;
        // entityHitLayer sits on top of entityLayer so its event handlers
        // survive when drawEntities rebuilds the visual layer every frame.
        app.stage.addChild(floorLayer, entityLayer, patronLayer, entityHitLayer);
        drawFloor(floorLayer, textures);
        seedEntityHitLayer(entityHitLayer, data.entities, onSelectRef);
        hostRef.current.appendChild(app.canvas);
        setPixiReady(true);
      })
      .catch((err: unknown) => {
        console.error('Failed to initialize Pixi application', err);
      });

    return () => {
      cancelled = true;
      if (initialized) {
        app.destroy(true);
      }
      appRef.current = null;
      floorLayerRef.current = null;
      entityLayerRef.current = null;
      entityHitLayerRef.current = null;
      patronLayerRef.current = null;
      texturesRef.current = null;
      patronRegistry.clear();
    };
    // Mount-once: floor sprite + hit overlay are seeded with the initial
    // entity set. The data.entities list is per-run but always 20 slots + bar,
    // so we don't need to re-seed on run switch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const hitLayer = entityHitLayerRef.current;
    if (!pixiReady || !hitLayer) return;
    seedEntityHitLayer(hitLayer, data.entities, onSelectRef);
  }, [data.entities, pixiReady]);

  useEffect(() => {
    const entityLayer = entityLayerRef.current;
    const textures = texturesRef.current;
    if (!pixiReady || !entityLayer || !textures) return;

    entityLayer.removeChildren();
    drawEntities(entityLayer, data.entities, selectedId, eventIds, events, machineStatus, textures, time);
  }, [data.entities, eventIds, events, machineStatus, onSelect, pixiReady, selectedId, time]);

  useEffect(() => {
    const patronLayer = patronLayerRef.current;
    if (!pixiReady || !patronLayer) return;
    updatePatronLayer({
      layer: patronLayer,
      registry: patronGraphicsRef.current,
      samplesByPatron,
      time,
      selectedId,
      eventIds,
      onSelect,
    });
  }, [eventIds, onSelect, pixiReady, samplesByPatron, selectedId, time]);

  return (
    <div className="overflow-auto bg-[radial-gradient(circle_at_50%_30%,rgba(245,158,11,0.12),transparent_38%),#020617] p-6">
      <div ref={hostRef} className="mx-auto w-fit rounded-2xl border border-amber-500/30 shadow-[0_0_60px_rgba(245,158,11,0.18)]" />
      <div className="mx-auto mt-3 flex w-fit flex-wrap items-center gap-3 rounded-full border border-slate-800 bg-slate-950/80 px-4 py-2 text-[11px] uppercase tracking-wide text-slate-300">
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-cyan-300 shadow-[0_0_10px_#67e8f9]" />Active patron</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-amber-300 shadow-[0_0_10px_#fcd34d]" />Event focus</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-rose-400 shadow-[0_0_10px_#fb7185]" />Machine alert</span>
      </div>
    </div>
  );
}

async function loadCasinoTextures(): Promise<CasinoTextures> {
  const [
    floorCarpetRed,
    floorCarpetBlue,
    floorCarpetPurple,
    wallTrimRed,
    plant,
    loungeTable,
    loungeChair,
    decorativeLamp,
    slotIdle,
    slotHot,
  ] = await Promise.all([
    Assets.load<Texture>(`${CASINO_ASSET_BASE}/floor-carpet-red.png`),
    Assets.load<Texture>(`${CASINO_ASSET_BASE}/floor-carpet-blue.png`),
    Assets.load<Texture>(`${CASINO_ASSET_BASE}/floor-carpet-purple.png`),
    Assets.load<Texture>(`${CASINO_ASSET_BASE}/wall-trim-red.png`),
    Assets.load<Texture>(`${CASINO_ASSET_BASE}/plant.png`),
    Assets.load<Texture>(`${CASINO_ASSET_BASE}/lounge-table.png`),
    Assets.load<Texture>(`${CASINO_ASSET_BASE}/lounge-chair.png`),
    Assets.load<Texture>(`${CASINO_ASSET_BASE}/decorative-lamp.png`),
    Assets.load<Texture>(`${CASINO_ASSET_BASE}/slot-idle.png`),
    Assets.load<Texture>(`${CASINO_ASSET_BASE}/slot-hot.png`),
  ]);

  return {
    floorCarpetRed,
    floorCarpetBlue,
    floorCarpetPurple,
    wallTrimRed,
    plant,
    loungeTable,
    loungeChair,
    decorativeLamp,
    slotIdle,
    slotHot,
  };
}

function drawFloor(stage: Container, textures: CasinoTextures) {
  const backplate = new Graphics();
  backplate.rect(0, 0, FLOOR_WIDTH * TILE_SIZE, FLOOR_HEIGHT * TILE_SIZE).fill(0x030712);
  stage.addChild(backplate);

  // Doorway tiles where the wall trim is replaced with carpet so patrons
  // appear to enter/exit through visible openings (matches the off-canvas
  // entrance positions used by the simulator).
  const isDoorway = (x: number, y: number) =>
    // South doors
    ((x === 4 || x === 5 || x === 14 || x === 15 || x === 23 || x === 24) && y === 19) ||
    // North doors
    ((x === 8 || x === 9 || x === 20 || x === 21) && (y === 0 || y === 1)) ||
    // West service door
    ((y === 15 || y === 16) && (x === 0 || x === 1)) ||
    // East service door
    ((y === 15 || y === 16) && (x === 28 || x === 29));

  for (let x = 0; x < FLOOR_WIDTH; x += 1) {
    for (let y = 0; y < FLOOR_HEIGHT; y += 1) {
      const isInside = x > 1 && x < 28 && y > 1 && y < 19;
      const isRunner = isInside && ((x >= 3 && x <= 4) || (x >= 13 && x <= 14) || (x >= 23 && x <= 24) || (y >= 15 && y <= 16));
      const isFeatureRug =
        isInside && ((x >= 5 && x <= 11 && y >= 3 && y <= 6) || (x >= 5 && x <= 11 && y >= 9 && y <= 12) || (x >= 14 && x <= 20 && y >= 3 && y <= 6) || (x >= 14 && x <= 20 && y >= 9 && y <= 12));
      const doorway = !isInside && isDoorway(x, y);
      const texture = doorway
        ? textures.floorCarpetBlue
        : !isInside
          ? textures.wallTrimRed
          : isRunner
            ? textures.floorCarpetBlue
            : isFeatureRug
              ? textures.floorCarpetPurple
              : textures.floorCarpetRed;
      addSprite(stage, texture, x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE);
    }
  }

  const floor = new Graphics();
  floor.rect(2 * TILE_SIZE, 2 * TILE_SIZE, 26 * TILE_SIZE, 0.55 * TILE_SIZE).fill(0x170617);
  floor.rect(2 * TILE_SIZE, 18.45 * TILE_SIZE, 26 * TILE_SIZE, 0.55 * TILE_SIZE).fill(0x170617);
  floor.rect(2 * TILE_SIZE, 2 * TILE_SIZE, 0.55 * TILE_SIZE, 17 * TILE_SIZE).fill(0x170617);
  floor.rect(27.45 * TILE_SIZE, 2 * TILE_SIZE, 0.55 * TILE_SIZE, 17 * TILE_SIZE).fill(0x170617);
  floor.rect(1.95 * TILE_SIZE, 15.05 * TILE_SIZE, 0.85 * TILE_SIZE, 1.75 * TILE_SIZE).fill(0x030712);
  floor.rect(27.2 * TILE_SIZE, 15.05 * TILE_SIZE, 0.85 * TILE_SIZE, 1.75 * TILE_SIZE).fill(0x030712);
  floor.rect(3.35 * TILE_SIZE, 18.35 * TILE_SIZE, 1.45 * TILE_SIZE, 0.65 * TILE_SIZE).fill(0x030712);
  floor.rect(25.2 * TILE_SIZE, 18.35 * TILE_SIZE, 1.45 * TILE_SIZE, 0.65 * TILE_SIZE).fill(0x030712);
  floor.roundRect(2.65 * TILE_SIZE, 15.65 * TILE_SIZE, 0.45 * TILE_SIZE, 0.55 * TILE_SIZE, 2).fill(0xf59e0b);
  floor.roundRect(26.9 * TILE_SIZE, 15.65 * TILE_SIZE, 0.45 * TILE_SIZE, 0.55 * TILE_SIZE, 2).fill(0xf59e0b);
  floor.roundRect(4.65 * TILE_SIZE, 2.8 * TILE_SIZE, 7 * TILE_SIZE, 0.36 * TILE_SIZE, 5).fill(0xf59e0b);
  floor.roundRect(13.7 * TILE_SIZE, 2.8 * TILE_SIZE, 7 * TILE_SIZE, 0.36 * TILE_SIZE, 5).fill(0xf59e0b);
  floor.roundRect(20.2 * TILE_SIZE, 2.55 * TILE_SIZE, 5.8 * TILE_SIZE, 0.35 * TILE_SIZE, 5).fill(0xfacc15);
  floor.roundRect(20.2 * TILE_SIZE, 8.2 * TILE_SIZE, 5.8 * TILE_SIZE, 0.24 * TILE_SIZE, 5).fill(0x38bdf8);
  floor.roundRect(2.65 * TILE_SIZE, 15.65 * TILE_SIZE, 22.5 * TILE_SIZE, 0.2 * TILE_SIZE, 3).fill({ color: 0xf59e0b, alpha: 0.62 });
  floor.roundRect(3.65 * TILE_SIZE, 3 * TILE_SIZE, 0.2 * TILE_SIZE, 13 * TILE_SIZE, 3).fill({ color: 0xf59e0b, alpha: 0.38 });
  floor.roundRect(13.65 * TILE_SIZE, 3 * TILE_SIZE, 0.2 * TILE_SIZE, 13 * TILE_SIZE, 3).fill({ color: 0xf59e0b, alpha: 0.38 });
  floor.roundRect(23.65 * TILE_SIZE, 3 * TILE_SIZE, 0.2 * TILE_SIZE, 13 * TILE_SIZE, 3).fill({ color: 0x38bdf8, alpha: 0.42 });
  floor.rect(0, 0, FLOOR_WIDTH * TILE_SIZE, FLOOR_HEIGHT * TILE_SIZE).stroke({ width: 3, color: 0x6b250f, alpha: 0.9 });
  stage.addChild(floor);

  drawStaticProps(stage, textures);
}

// Build a stable click overlay: one transparent rect per clickable entity
// with a pointertap handler. The rest of the entity visuals re-render every
// frame, but these hit-test rectangles never get destroyed, so clicks
// always land — including while the replay is playing.
function seedEntityHitLayer(
  layer: Container,
  entities: FloorEntity[],
  onSelectRef: { current: (id: string) => void },
) {
  layer.removeChildren();
  for (const entity of entities) {
    if (entity.entity_type !== 'machine' && entity.entity_type !== 'bar') continue;
    const ex = Number(entity.x) * TILE_SIZE;
    const ey = Number(entity.y) * TILE_SIZE;
    const ew = Number(entity.width) * TILE_SIZE;
    const eh = Number(entity.height) * TILE_SIZE;
    // For slot machines the visible sprite extends upward from the entity
    // tile (spriteHeight ≈ 2.45 tiles). Expand the hit rect to cover it.
    const hit = new Graphics();
    if (entity.entity_type === 'machine') {
      const spriteHeight = TILE_SIZE * 2.45;
      const spriteWidth = TILE_SIZE * 1.22;
      hit.rect(
        ex + (ew - spriteWidth) / 2,
        ey + eh - spriteHeight,
        spriteWidth,
        spriteHeight + TILE_SIZE * 0.2,
      ).fill({ color: 0xffffff, alpha: 0.001 });
    } else {
      hit.rect(ex, ey, ew, eh).fill({ color: 0xffffff, alpha: 0.001 });
    }
    hit.eventMode = 'static';
    hit.cursor = 'pointer';
    hit.on('pointertap', () => onSelectRef.current(entity.entity_id));
    layer.addChild(hit);
  }
}

function drawEntities(
  stage: Container,
  entities: FloorEntity[],
  selectedId: string | null,
  eventIds: string[],
  events: ActivityEvent[],
  machineStatus: Map<string, string>,
  textures: CasinoTextures,
  time: number,
) {
  for (const entity of entities) {
    const x = Number(entity.x) * TILE_SIZE;
    const y = Number(entity.y) * TILE_SIZE;
    const width = Number(entity.width) * TILE_SIZE;
    const height = Number(entity.height) * TILE_SIZE;
    const isSelected = selectedId === entity.entity_id;
    const isHot = eventIds.includes(entity.entity_id);
    const focusEvent = events.find((event) => event.machine_id === entity.entity_id || event.entity_id === entity.entity_id);
    const isJackpot = focusEvent?.event_type === 'JACKPOT_HANDPAY';
    const status = machineStatus.get(entity.entity_id) ?? 'IN_SERVICE';
    const isFaulted = status !== 'IN_SERVICE';
    const isHardFault = status === 'BILL_VALIDATOR_FAULT' || status === 'OUT_OF_SERVICE' || status === 'DOOR_OPEN';
    const graphic = new Graphics();
    const pulse = 0.5 + Math.sin(time * 5 + x * 0.05) * 0.5;

    if (entity.entity_type === 'machine') {
      const spriteWidth = TILE_SIZE * 1.22;
      const spriteHeight = TILE_SIZE * 2.45;
      graphic
        .ellipse(x + width / 2, y + height + 0.14 * TILE_SIZE, width * 0.72, TILE_SIZE * 0.2)
        .fill({ color: 0x000000, alpha: 0.42 });
      // Persistent fault ring stays visible the whole time the machine is
      // not IN_SERVICE — not just when a MACHINE_STATUS event is in the
      // ±4s event window. Centered on the visible sprite (the slot tower
      // extends upward from the entity tile).
      const spriteCenterY = y + height - spriteHeight / 2;
      if (isFaulted) {
        const ringColor = isHardFault ? 0xfb7185 : 0xfacc15;
        graphic
          .ellipse(x + width / 2, spriteCenterY, TILE_SIZE * (1.15 + pulse * 0.15), TILE_SIZE * (1.55 + pulse * 0.18))
          .stroke({ width: 2.5, color: ringColor, alpha: 0.7 + pulse * 0.2 });
        graphic
          .ellipse(x + width / 2, spriteCenterY, TILE_SIZE * 0.95, TILE_SIZE * 1.35)
          .fill({ color: ringColor, alpha: 0.12 + pulse * 0.06 });
      }
      if ((isHot && !isFaulted) || isSelected) {
        graphic
          .circle(x + width / 2, y, TILE_SIZE * (0.72 + pulse * 0.12))
          .fill({ color: isHot ? 0xfacc15 : 0x67e8f9, alpha: isHot ? 0.18 + pulse * 0.12 : 0.14 });
      }
      if (isJackpot) {
        drawJackpotBurst(graphic, x + width / 2, y - TILE_SIZE * 0.35, pulse);
      }
      if (isSelected) {
        graphic.ellipse(x + width / 2, y + height * 0.94, width * 0.78, TILE_SIZE * 0.28).stroke({
          width: 2,
          color: 0xffffff,
          alpha: 0.85,
        });
      }
      stage.addChild(graphic);

      const sprite = addSprite(
        stage,
        isHot ? textures.slotHot : textures.slotIdle,
        x + (width - spriteWidth) / 2,
        y + height - spriteHeight,
        spriteWidth,
        spriteHeight,
      );
      // OUT_OF_SERVICE / DOOR_OPEN slots get desaturated so they read as down.
      if (status === 'OUT_OF_SERVICE' || status === 'DOOR_OPEN') {
        sprite.tint = 0x556677;
        sprite.alpha = 0.75;
      } else if (status === 'BILL_VALIDATOR_FAULT' || status === 'SOFT_FAULT') {
        sprite.tint = 0xffd0d0;
      }

      const topper = new Graphics();
      const topperColor = isFaulted
        ? isHardFault
          ? 0xfb7185
          : 0xfacc15
        : isHot
          ? 0xffffff
          : 0xfbbf24;
      topper.circle(x + width / 2, y - TILE_SIZE * 0.78, 2.5).fill(topperColor);
      topper.circle(x + width / 2, y - TILE_SIZE * 0.78, 5 + pulse * 2).fill({ color: topperColor, alpha: isHot || isFaulted ? 0.25 : 0.08 });
      stage.addChild(topper);
      continue;
    } else if (entity.entity_type === 'bar') {
      // Bar zone occupies a 6×5 tile footprint. Lay it out top-to-bottom as
      // back wall → shelves → counter → stools so it actually reads as a bar.
      const T = TILE_SIZE;
      const innerW = width - T * 0.4;
      const baseX = x + T * 0.2;
      const backWallY = y + T * 0.05;
      const shelfTopY = y + T * 0.5;
      const counterTopY = y + T * 1.9;
      const counterBottomY = y + T * 2.6;
      const stoolY = y + T * 3.4;
      const seatCount = 6;

      // Floor shadow under the whole zone
      graphic
        .roundRect(baseX, backWallY, innerW, height - T * 0.4, 12)
        .fill({ color: 0x0b0612, alpha: 0.55 });

      // Back wall mirror panel (deep purple with neon glow)
      graphic
        .roundRect(baseX + T * 0.05, backWallY, innerW - T * 0.1, T * 1.45, 8)
        .fill(0x1c0b2a)
        .stroke({ width: isSelected ? 3 : 1, color: isSelected ? 0xffffff : 0x9333ea, alpha: 0.7 });
      // Neon "NEON BAR" sign band
      graphic
        .roundRect(baseX + T * 0.25, backWallY + T * 0.12, innerW - T * 0.5, T * 0.35, 4)
        .fill({ color: 0x67e8f9, alpha: 0.18 })
        .stroke({ width: 1, color: 0x22d3ee, alpha: 0.85 });

      // Two shelves of bottles
      for (const shelfOffset of [0.55, 0.95]) {
        graphic
          .rect(baseX + T * 0.2, shelfTopY + T * shelfOffset, innerW - T * 0.4, T * 0.06)
          .fill(0x4a1d08);
        for (let bottle = 0; bottle < 14; bottle += 1) {
          const bottleX = baseX + T * (0.35 + bottle * (innerW / T - 0.7) / 14);
          const bottleH = T * (0.25 + ((bottle * 17) % 5) * 0.04);
          const bottleColor = [0x22c55e, 0x38bdf8, 0xf59e0b, 0xef4444, 0xa855f7][bottle % 5];
          graphic
            .roundRect(bottleX, shelfTopY + T * shelfOffset - bottleH, T * 0.16, bottleH, 1.2)
            .fill(bottleColor)
            .rect(bottleX + T * 0.05, shelfTopY + T * shelfOffset - bottleH - T * 0.03, T * 0.06, T * 0.04)
            .fill(0xc7c7c7);
        }
      }

      // Bar counter (horizontal slab)
      graphic
        .roundRect(baseX, counterTopY, innerW, counterBottomY - counterTopY, 8)
        .fill(0x4a1d08)
        .stroke({ width: 1, color: 0xfbbf24, alpha: 0.7 });
      // Brass rail highlight
      graphic
        .rect(baseX + T * 0.15, counterTopY + T * 0.08, innerW - T * 0.3, T * 0.08)
        .fill({ color: 0xfacc15, alpha: 0.85 });
      // Drink rail (darker)
      graphic
        .rect(baseX + T * 0.15, counterBottomY - T * 0.14, innerW - T * 0.3, T * 0.08)
        .fill(0x2a1108);

      // Row of stools
      const stoolSpacing = innerW / (seatCount + 1);
      for (let seat = 0; seat < seatCount; seat += 1) {
        const seatX = baseX + stoolSpacing * (seat + 1);
        // Stool shadow
        graphic.ellipse(seatX, stoolY + T * 0.55, T * 0.16, T * 0.06).fill({ color: 0x000000, alpha: 0.4 });
        // Stool post
        graphic.rect(seatX - T * 0.04, stoolY + T * 0.15, T * 0.08, T * 0.35).fill(0x1f1612);
        // Stool seat
        graphic
          .circle(seatX, stoolY + T * 0.12, T * 0.22)
          .fill(0x9a3412)
          .stroke({ width: 1, color: 0xfbbf24, alpha: 0.9 });
      }
    } else {
      continue;
    }

    stage.addChild(graphic);
  }
}

function drawJackpotBurst(graphic: Graphics, x: number, y: number, pulse: number) {
  const radius = TILE_SIZE * (0.95 + pulse * 0.25);
  graphic.circle(x, y, radius).stroke({ width: 2, color: 0xfacc15, alpha: 0.75 });
  for (let i = 0; i < 10; i += 1) {
    const angle = (Math.PI * 2 * i) / 10 + pulse * 0.6;
    const sparkleX = x + Math.cos(angle) * radius;
    const sparkleY = y + Math.sin(angle) * radius * 0.72;
    graphic.circle(sparkleX, sparkleY, 2 + pulse * 1.4).fill({ color: i % 2 === 0 ? 0xffffff : 0xfacc15, alpha: 0.82 });
  }
}

function drawStaticProps(stage: Container, textures: CasinoTextures) {
  addGlow(stage, 22.9 * TILE_SIZE, 5.55 * TILE_SIZE, 112, 62, 0x38bdf8, 0.13);
  addGlow(stage, 8.4 * TILE_SIZE, 4.7 * TILE_SIZE, 120, 46, 0xf59e0b, 0.08);
  addGlow(stage, 16.4 * TILE_SIZE, 10.7 * TILE_SIZE, 120, 46, 0xf59e0b, 0.08);

  // Corner plants frame the floor; the central lounge cluster reads as broken
  // furniture rather than seating, so we omit those props for now.
  addSprite(stage, textures.plant, 2.9 * TILE_SIZE, 2.8 * TILE_SIZE, TILE_SIZE * 1.0, TILE_SIZE * 2.0);
  addSprite(stage, textures.plant, 25.8 * TILE_SIZE, 15.7 * TILE_SIZE, TILE_SIZE * 1.0, TILE_SIZE * 2.0);
  addSprite(stage, textures.plant, 2.9 * TILE_SIZE, 15.7 * TILE_SIZE, TILE_SIZE * 1.0, TILE_SIZE * 2.0);

  const labels = [
    { text: 'JACKPOT ROW', x: 5.1, y: 2.95, color: 0xfacc15 },
    { text: 'LUCKY LANTERNS', x: 14.2, y: 2.95, color: 0xfacc15 },
    { text: 'NEON BAR', x: 21.1, y: 2.93, color: 0x67e8f9 },
  ];
  for (const label of labels) {
    const text = new Text({
      text: label.text,
      style: { fill: label.color, fontFamily: 'monospace', fontSize: 10, fontWeight: '700' },
    });
    text.x = label.x * TILE_SIZE;
    text.y = label.y * TILE_SIZE;
    stage.addChild(text);
  }
}

function addGlow(stage: Container, x: number, y: number, width: number, height: number, color: number, alpha: number) {
  const glow = new Graphics();
  glow.ellipse(x, y, width, height).fill({ color, alpha });
  stage.addChild(glow);
}

function addSprite(stage: Container, texture: Texture, x: number, y: number, width: number, height: number) {
  const sprite = new Sprite(texture);
  sprite.x = Math.round(x);
  sprite.y = Math.round(y);
  sprite.width = Math.round(width);
  sprite.height = Math.round(height);
  sprite.roundPixels = true;
  stage.addChild(sprite);
  return sprite;
}

const PATRON_HAIR_PALETTE = [0x2b1a0b, 0x4a2a13, 0x6b3b1a, 0xa66230, 0xc9913a, 0xdedede, 0x1a1a1a];
const PATRON_SKIN_PALETTE = [0xf4c89a, 0xe7b687, 0xd29563, 0xa46a3e, 0x7a4a2b, 0xf8d8b3];
const PATRON_PANT_PALETTE = [0x1f2937, 0x312e81, 0x4b5563, 0x111827, 0x3f3f46, 0x451a03];
const FLOOR_INNER = { minX: 2.1, maxX: 27.9, minY: 2.1, maxY: 18.9 };

function hashStringToInt(value: string) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
  }
  return hash;
}

function lightenColor(color: number, amount: number) {
  const r = Math.min(255, ((color >> 16) & 0xff) + amount);
  const g = Math.min(255, ((color >> 8) & 0xff) + amount);
  const b = Math.min(255, (color & 0xff) + amount);
  return (r << 16) | (g << 8) | b;
}

function darkenColor(color: number, amount: number) {
  const r = Math.max(0, ((color >> 16) & 0xff) - amount);
  const g = Math.max(0, ((color >> 8) & 0xff) - amount);
  const b = Math.max(0, (color & 0xff) - amount);
  return (r << 16) | (g << 8) | b;
}

function updatePatronLayer({
  layer,
  registry,
  samplesByPatron,
  time,
  selectedId,
  eventIds,
  onSelect,
}: {
  layer: Container;
  registry: Map<string, Graphics>;
  samplesByPatron: Map<string, ReplaySample[]>;
  time: number;
  selectedId: string | null;
  eventIds: string[];
  onSelect: (patronId: string) => void;
}) {
  const seen = new Set<string>();
  const eventIdSet = new Set(eventIds);

  for (const [patronId, samples] of samplesByPatron) {
    const position = interpolateSample(samples, time);
    if (!position) continue;
    seen.add(patronId);
    let graphics = registry.get(patronId);
    if (!graphics) {
      graphics = new Graphics();
      graphics.eventMode = 'static';
      graphics.cursor = 'pointer';
      graphics.on('pointertap', () => onSelect(patronId));
      registry.set(patronId, graphics);
      layer.addChild(graphics);
    }
    paintPatron(
      graphics,
      patronId,
      position,
      time,
      selectedId === patronId,
      eventIdSet.has(patronId),
    );
  }

  for (const [patronId, graphics] of registry) {
    if (seen.has(patronId)) continue;
    layer.removeChild(graphics);
    graphics.destroy();
    registry.delete(patronId);
  }
}

function paintPatron(
  marker: Graphics,
  patronId: string,
  position: ReplaySample,
  time: number,
  isSelected: boolean,
  isHot: boolean,
) {
  marker.clear();
  const tileX = Number(position.x);
  const tileY = Number(position.y);
  const px = tileX * TILE_SIZE;
  const py = tileY * TILE_SIZE;
  // Soft alpha fade when patrons are walking through the wall band (between
  // the floor edge and the canvas edge) — they read as "approaching the
  // doorway" rather than abruptly popping in.
  const inEdgeBand =
    tileX < FLOOR_INNER.minX ||
    tileX > FLOOR_INNER.maxX ||
    tileY < FLOOR_INNER.minY ||
    tileY > FLOOR_INNER.maxY;
  marker.alpha = inEdgeBand ? 0.55 : 1;
  const activity = position.activity;
  const isWalking = activity === 'WALKING' || activity === 'EXITING' || activity === 'PASSING_THROUGH';
  const isFacingEast = position.facing === 'east';
  const isFacingWest = position.facing === 'west';
  const isFacingNorth = position.facing === 'north';

  const hash = hashStringToInt(patronId);
  const shirtColor = parseColor(typeof position.metadata.color === 'string' ? position.metadata.color : '#40d1f5');
  const skin = PATRON_SKIN_PALETTE[hash % PATRON_SKIN_PALETTE.length];
  const hair = PATRON_HAIR_PALETTE[(hash >>> 3) % PATRON_HAIR_PALETTE.length];
  const pants = PATRON_PANT_PALETTE[(hash >>> 6) % PATRON_PANT_PALETTE.length];
  const shirtDark = darkenColor(shirtColor, 60);
  const shirtLight = lightenColor(shirtColor, 25);

  const stepPhase = isWalking ? Math.sin(time * 9 + (hash % 100) * 0.07) : 0;
  const bob = isWalking ? Math.abs(stepPhase) * 1.6 - 0.8 : 0;
  const armSwing = isWalking ? stepPhase * 2.6 : 0;
  const legSplay = isWalking ? Math.sign(stepPhase) * 2 : 0;
  const sittingTucked = activity === 'PLAYING_SLOT' || activity === 'AT_BAR';

  // Footprint anchored at (px, py): py is the patron's feet on the tile.
  const feetY = py - 0.5;
  const headRadius = 4.5;
  const torsoWidth = 9;
  const torsoHeight = 10;
  const headCenterY = feetY - 18 + bob;
  const torsoY = headCenterY + headRadius - 1;
  const hipY = torsoY + torsoHeight - 1;

  // Soft contact shadow.
  marker.ellipse(px, feetY + 1, 7, 2.4).fill({ color: 0x000000, alpha: 0.45 });

    // Legs / pants. When sitting at slot or bar, draw a short stool stub instead.
    if (sittingTucked) {
      marker
        .roundRect(px - 4, hipY, 8, 6, 1)
        .fill(pants)
        .roundRect(px - 5, hipY + 5, 10, 2, 1)
        .fill(darkenColor(pants, 40));
    } else {
      const leftLegX = px - 3 - legSplay * 0.3;
      const rightLegX = px + 0 + legSplay * 0.3;
      marker
        .roundRect(leftLegX, hipY, 3, 7 + legSplay, 1)
        .fill(pants)
        .roundRect(rightLegX, hipY, 3, 7 - legSplay, 1)
        .fill(pants)
        // shoes
        .roundRect(leftLegX - 0.5, hipY + 7 + legSplay - 1, 4, 1.8, 0.6)
        .fill(0x1a1a1a)
        .roundRect(rightLegX - 0.5, hipY + 7 - legSplay - 1, 4, 1.8, 0.6)
        .fill(0x1a1a1a);
    }

    // Torso (shirt) with subtle shading.
    marker
      .roundRect(px - torsoWidth / 2, torsoY, torsoWidth, torsoHeight, 2)
      .fill(shirtColor)
      .roundRect(px - torsoWidth / 2, torsoY, torsoWidth, 2.2, 2)
      .fill(shirtLight)
      .roundRect(px - torsoWidth / 2, torsoY + torsoHeight - 2, torsoWidth, 2, 2)
      .fill(shirtDark);

    // Arms.
    if (!sittingTucked) {
      const leftArmDx = isFacingEast ? -2.5 : isFacingWest ? -2.5 : -5;
      const rightArmDx = isFacingEast ? 5 : isFacingWest ? 5 : 5;
      marker
        .roundRect(px + leftArmDx - 1, torsoY + 1 + armSwing * 0.4, 2, 7 - Math.abs(armSwing) * 0.2, 1)
        .fill(shirtDark)
        .roundRect(px + rightArmDx - 1, torsoY + 1 - armSwing * 0.4, 2, 7 - Math.abs(armSwing) * 0.2, 1)
        .fill(shirtDark);
      // hands
      marker
        .circle(px + leftArmDx, torsoY + 8 + armSwing * 0.4, 1.5)
        .fill(skin)
        .circle(px + rightArmDx, torsoY + 8 - armSwing * 0.4, 1.5)
        .fill(skin);
    } else {
      // Hands resting on a control deck / bar lip.
      marker
        .circle(px - 5, torsoY + 4, 1.6)
        .fill(skin)
        .circle(px + 5, torsoY + 4, 1.6)
        .fill(skin);
    }

    // Head.
    marker.circle(px, headCenterY, headRadius).fill(skin);
    // Hair / cap. If facing north, hair covers most of the head; otherwise
    // it's a tighter cap leaving a face arc visible.
    if (isFacingNorth) {
      marker.circle(px, headCenterY - 0.5, headRadius - 0.2).fill(hair);
    } else {
      marker
        .roundRect(px - headRadius, headCenterY - headRadius, headRadius * 2, headRadius + 0.5, 2)
        .fill(hair);
    }
    // Eyes (only when not facing north).
    if (!isFacingNorth) {
      const eyeOffset = isFacingEast ? 1.5 : isFacingWest ? -1.5 : 0;
      if (isFacingEast || isFacingWest) {
        marker.circle(px + eyeOffset, headCenterY + 1, 0.7).fill(0x111111);
      } else {
        marker
          .circle(px - 1.4, headCenterY + 1, 0.7)
          .fill(0x111111)
          .circle(px + 1.4, headCenterY + 1, 0.7)
          .fill(0x111111);
      }
    }

    // Activity glyph above head: yellow chip when playing, blue bubble at bar.
    if (activity === 'PLAYING_SLOT') {
      marker.circle(px, headCenterY - headRadius - 3, 1.5).fill(0xfacc15);
    } else if (activity === 'AT_BAR') {
      marker
        .roundRect(px - 1.5, headCenterY - headRadius - 5, 3, 4, 0.6)
        .fill(0x38bdf8)
        .rect(px - 0.6, headCenterY - headRadius - 6, 1.2, 1)
        .fill(0xa5f3fc);
    }

  if (isSelected || isHot) {
    const ringColor = isHot ? 0xfacc15 : 0x67e8f9;
    marker
      .ellipse(px, feetY + 1, 12, 3.5)
      .stroke({ width: 1.5, color: ringColor, alpha: 0.9 })
      .ellipse(px, feetY + 1, 16, 5)
      .stroke({ width: 1, color: ringColor, alpha: 0.35 });
  }
}

function interpolateSample(samples: ReplaySample[], time: number): ReplaySample | null {
  const ordered = [...samples].sort((a, b) => Number(a.sim_second) - Number(b.sim_second));
  const previous = [...ordered].reverse().find((sample) => Number(sample.sim_second) <= time);
  const next = ordered.find((sample) => Number(sample.sim_second) >= time);
  if (!previous && !next) return null;
  if (!previous) return next ?? null;
  if (!next) return previous;

  const previousTime = Number(previous.sim_second);
  const nextTime = Number(next.sim_second);
  if (previousTime === nextTime) return previous;

  const progress = (time - previousTime) / (nextTime - previousTime);
  return {
    ...previous,
    x: Number(previous.x) + (Number(next.x) - Number(previous.x)) * progress,
    y: Number(previous.y) + (Number(next.y) - Number(previous.y)) * progress,
  };
}

function parseColor(value: string) {
  return Number.parseInt(value.replace('#', ''), 16);
}
