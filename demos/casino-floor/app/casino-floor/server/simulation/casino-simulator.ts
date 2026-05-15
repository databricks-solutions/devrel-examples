// Casino-floor tick simulator. Replaces the route-segment generator with a
// continuous state-machine loop so patrons disperse naturally, machines have
// occupancy + status + meters, and BET_SETTLED / JACKPOT_HANDPAY / METER_POLL
// events come from the same state transitions that drive the replay.
//
// Determinism: all randomness flows through a seeded RNG keyed on
// `(scenario.seed, stream)` so a run can be regenerated bit-for-bit.

export type Volatility = 'LOW' | 'MEDIUM' | 'HIGH';
export type MachineStatus =
  | 'IN_SERVICE'
  | 'SOFT_FAULT'
  | 'BILL_VALIDATOR_FAULT'
  | 'DOOR_OPEN'
  | 'OUT_OF_SERVICE';

export interface MachineConfig {
  machineId: string;
  bankId: string;
  x: number;
  y: number;
  width: number;
  height: number;
  theme: string;
  paytableId: string;
  denominationCents: number;
  volatility: Volatility;
  theoreticalHoldPct: number;
}

export interface ScenarioConfig {
  durationSeconds: number;
  patronCount: number;
  arrivalIntervalSeconds: number;
  seed: number;
  faultRate: number;
  jackpotMultiplier: number;
  barAttractiveness: number;
  configChanges?: ScenarioConfigChange[];
}

export interface ScenarioConfigChange {
  atSimSecond: number;
  machineId: string;
  newPaytableId: string;
  newTheoreticalHoldPct: number;
  newVolatility?: Volatility;
}

export interface SimulationOutput {
  samples: SampleRow[];
  events: EventRow[];
  meterPolls: MeterPollRow[];
}

export interface SampleRow {
  simSecond: number;
  entityId: string;
  entityType: 'patron';
  x: number;
  y: number;
  facing: 'north' | 'south' | 'east' | 'west';
  activity: string;
  status: string | null;
  targetId: string | null;
  metadata: Record<string, unknown>;
}

export interface EventRow {
  eventId: string;
  simSecond: number;
  eventType: string;
  entityId: string | null;
  patronId: string | null;
  machineId: string | null;
  title: string;
  description: string;
  payload: Record<string, unknown>;
}

export interface MeterPollRow {
  simSecond: number;
  machineId: string;
  meters: Record<string, number>;
}

interface PatronState {
  id: string;
  color: string;
  label: string;
  behavior: string;
  bankrollCents: number;
  walletCents: number;
  preferenceVolatility: Volatility | null;
  preferenceDenomCents: number | null;
  visitsBar: boolean;
  patienceSeconds: number;
  betCadenceSeconds: number;
  arrivesAt: number;
  spawnPoint: Point;
  exitPoint: Point;
  position: Point;
  facing: 'north' | 'south' | 'east' | 'west';
  state:
    | 'OFFSCREEN'
    | 'WALKING_TO_SLOT'
    | 'PLAYING_SLOT'
    | 'WALKING_TO_BAR'
    | 'AT_BAR'
    | 'WAITING'
    | 'EXITING'
    | 'GONE';
  target: Point | null;
  targetId: string | null;
  waypoints: Point[];
  assignedMachineId: string | null;
  sessionId: string | null;
  sessionStartedAt: number | null;
  sessionPlayPlannedSeconds: number;
  lastBetAt: number;
  hasVisitedBar: boolean;
  faultsAbandoned: number;
}

interface MachineRuntimeState {
  config: MachineConfig;
  status: MachineStatus;
  occupantId: string | null;
  faultUntil: number | null;
  // Snake_case to match the canonical accounting field names from SCOPING.md
  // and the rest of the slot-monitoring vocabulary.
  meters: {
    coin_in_cents: number;
    coin_out_cents: number;
    jackpot_handpay_cents: number;
    progressive_contribution_cents: number;
    bill_in_cents: number;
    voucher_in_cents: number;
    voucher_out_cents: number;
    games_played: number;
  };
  // Live machine credits (cash-in − bets − ticket-out + wins) so the TITO flow
  // produces accurate voucher_out values at session end.
  creditCents: number;
}

interface ProgressivePool {
  meterCents: number;
  seedCents: number;
}

interface Point {
  x: number;
  y: number;
}

const TICK_SECONDS = 0.5;
const SAMPLE_INTERVAL_SECONDS = 0.5;
const METER_POLL_INTERVAL_SECONDS = 30;
const WALK_SPEED_TILES_PER_SECOND = 1.1;

const VOLATILITY_PROFILES: Record<
  Volatility,
  { hitProb: number; avgMultiplierIfHit: number; jackpotChance: number; jackpotMultiplier: number }
> = {
  // Real progressive jackpots are 1-in-tens-of-thousands events. We rarely
  // care that they match reality; we care that they appear 1-3 times per demo
  // run as dramatic events without dominating the hold metric. With 600s
  // runs giving ~8-15 bets/machine/minute, these rates produce ~1-3 hits
  // total on a single-multiplier scenario.
  LOW: { hitProb: 0.46, avgMultiplierIfHit: 2.01, jackpotChance: 0, jackpotMultiplier: 0 },
  MEDIUM: { hitProb: 0.26, avgMultiplierIfHit: 3.55, jackpotChance: 0.0015, jackpotMultiplier: 80 },
  HIGH: { hitProb: 0.12, avgMultiplierIfHit: 7.5, jackpotChance: 0.004, jackpotMultiplier: 220 },
};

// Off-canvas spawn points, each paired with an "approach node" just inside
// the wall band. Patrons walk from the off-canvas spawn to the approach node,
// then follow the aisle corridors to their target. Exit reverses the flow.
const DOORS: { spawn: Point; approach: Point }[] = [
  { spawn: { x: -2.5, y: 16 }, approach: { x: 2.5, y: 16 } },
  { spawn: { x: 32.5, y: 16 }, approach: { x: 27.5, y: 16 } },
  { spawn: { x: 5, y: 22.5 }, approach: { x: 5, y: 18.5 } },
  { spawn: { x: 15, y: 22.5 }, approach: { x: 15, y: 18.5 } },
  { spawn: { x: 24, y: 22.5 }, approach: { x: 24, y: 18.5 } },
  { spawn: { x: 9, y: -2.5 }, approach: { x: 9, y: 2.5 } },
  { spawn: { x: 21, y: -2.5 }, approach: { x: 21, y: 2.5 } },
];

const ENTRANCES: Point[] = DOORS.map((d) => d.spawn);

// Six stools along the front of the bar counter; patrons pick one based on
// patron id hash so a wave of bar visitors actually spreads along the bar.
const BAR_STOOLS: Point[] = [21.0, 21.8, 22.6, 23.4, 24.2, 25.0].map((x) => ({ x, y: 7.4 }));

function pickBarSeat(patronId: string): Point {
  let hash = 0;
  for (let i = 0; i < patronId.length; i += 1) hash = (hash * 31 + patronId.charCodeAt(i)) >>> 0;
  return { ...BAR_STOOLS[hash % BAR_STOOLS.length] };
}

// Major aisles. Patrons route via the corridor closest to the natural path
// so they don't cut through machine banks.
const VERTICAL_AISLES = [3.5, 12.85, 22.0];

function planRoute(start: Point, target: Point): Point[] {
  // For travel between floor zones, route via the nearest sensible corridor.
  // For very short hops (same row), skip the detour.
  const dx = target.x - start.x;
  const dy = target.y - start.y;
  if (Math.hypot(dx, dy) < 2.5) return [{ ...target }];
  const startNearTop = start.y < 8;
  const targetNearTop = target.y < 8;
  const startNearMid = start.y >= 8 && start.y < 13;
  const targetNearMid = target.y >= 8 && target.y < 13;
  let corridorY: number;
  if (startNearTop && targetNearTop) corridorY = 3.2;
  else if (startNearMid || targetNearMid) corridorY = 7.5;
  else if (start.y > 13 && target.y > 13) corridorY = 17.0;
  else corridorY = 7.5;
  // Snap to nearest vertical aisle if start.x is inside a bank column.
  const aisleAtX = (x: number) =>
    VERTICAL_AISLES.reduce((best, candidate) =>
      Math.abs(candidate - x) < Math.abs(best - x) ? candidate : best,
    );
  const startInBank = isInsideBankColumn(start.x);
  const targetInBank = isInsideBankColumn(target.x);
  const wps: Point[] = [];
  if (startInBank) wps.push({ x: aisleAtX(start.x), y: start.y });
  if (Math.abs(start.y - corridorY) > 0.5) wps.push({ x: (startInBank ? aisleAtX(start.x) : start.x), y: corridorY });
  if (Math.abs(start.x - target.x) > 0.5) wps.push({ x: (targetInBank ? aisleAtX(target.x) : target.x), y: corridorY });
  if (targetInBank) wps.push({ x: aisleAtX(target.x), y: target.y });
  wps.push({ ...target });
  return wps;
}

function isInsideBankColumn(x: number) {
  return (x >= 5.0 && x <= 11.8) || (x >= 13.9 && x <= 20.7);
}

function nearestDoor(point: Point): { spawn: Point; approach: Point } {
  let best = DOORS[0];
  let bestDist = Number.POSITIVE_INFINITY;
  for (const door of DOORS) {
    const d = Math.hypot(door.spawn.x - point.x, door.spawn.y - point.y);
    if (d < bestDist) {
      bestDist = d;
      best = door;
    }
  }
  return best;
}

function buildWalkPath(
  start: Point,
  target: Point,
  entry: 'enter' | 'none',
  exit: 'exit' | 'none',
): Point[] {
  const wps: Point[] = [];
  let cursor = start;
  if (entry === 'enter') {
    const door = nearestDoor(start);
    wps.push({ ...door.approach });
    cursor = door.approach;
  }
  const corridorEnd: Point = exit === 'exit' ? { ...nearestDoor(target).approach } : target;
  for (const wp of planRoute(cursor, corridorEnd)) {
    wps.push(wp);
  }
  return wps;
}

export function simulate(
  scenario: ScenarioConfig,
  machineConfigs: MachineConfig[],
): SimulationOutput {
  const rngPatrons = mulberry32(scenario.seed ^ 0x7f93b1);
  const rngOutcomes = mulberry32(scenario.seed ^ 0x05ed90);
  const rngFaults = mulberry32(scenario.seed ^ 0x11ff63);

  const machineStates = new Map<string, MachineRuntimeState>();
  for (const config of machineConfigs) {
    machineStates.set(config.machineId, {
      config,
      status: 'IN_SERVICE',
      occupantId: null,
      faultUntil: null,
      meters: {
        coin_in_cents: 0,
        coin_out_cents: 0,
        jackpot_handpay_cents: 0,
        progressive_contribution_cents: 0,
        bill_in_cents: 0,
        voucher_in_cents: 0,
        voucher_out_cents: 0,
        games_played: 0,
      },
      creditCents: 0,
    });
  }

  // Shared progressive jackpot pool. Each eligible spin adds its
  // progressive_contribution; a jackpot hit awards the pool and resets to seed.
  // Aligns with `data/manuals/progressive-rules.md`.
  const progressivePool: ProgressivePool = { meterCents: 10_000, seedCents: 10_000 };

  // Seed one bill-validator fault on a chosen machine to give the demo a
  // recognizable maintenance narrative. The patron whose session is on that
  // machine will abandon early and nearby machines should pick up the slack.
  const faultyCandidate = machineConfigs[7] ?? null;
  if (faultyCandidate) {
    const state = machineStates.get(faultyCandidate.machineId);
    if (state) state.faultUntil = 70;
  }

  const patrons: PatronState[] = [];
  for (let i = 0; i < scenario.patronCount; i += 1) {
    patrons.push(buildPatron(i, scenario, rngPatrons));
  }

  const samples: SampleRow[] = [];
  const events: EventRow[] = [];
  const meterPolls: MeterPollRow[] = [];
  let eventSeq = 0;
  const emit = (
    simSecond: number,
    eventType: string,
    args: {
      patronId?: string | null;
      machineId?: string | null;
      title: string;
      description: string;
      payload?: Record<string, unknown>;
    },
  ) => {
    eventSeq += 1;
    events.push({
      eventId: `${eventType.toLowerCase()}-${eventSeq.toString().padStart(5, '0')}`,
      simSecond: Number(simSecond.toFixed(2)),
      eventType,
      entityId: args.machineId ?? args.patronId ?? null,
      patronId: args.patronId ?? null,
      machineId: args.machineId ?? null,
      title: args.title,
      description: args.description,
      payload: args.payload ?? {},
    });
  };

  let nextSampleAt = 0;
  let nextMeterPollAt = METER_POLL_INTERVAL_SECONDS;
  const pendingConfigChanges = [...(scenario.configChanges ?? [])].sort(
    (a, b) => a.atSimSecond - b.atSimSecond,
  );

  for (let t = 0; t <= scenario.durationSeconds + TICK_SECONDS / 2; t += TICK_SECONDS) {
    const now = Number(t.toFixed(3));

    // Apply scheduled config changes (paytable swap mid-shift).
    while (pendingConfigChanges.length > 0 && pendingConfigChanges[0].atSimSecond <= now) {
      const change = pendingConfigChanges.shift()!;
      const target = machineStates.get(change.machineId);
      if (target) {
        const previous = {
          paytable_id: target.config.paytableId,
          theoretical_hold_pct: target.config.theoreticalHoldPct,
          volatility: target.config.volatility,
        };
        target.config = {
          ...target.config,
          paytableId: change.newPaytableId,
          theoreticalHoldPct: change.newTheoreticalHoldPct,
          volatility: change.newVolatility ?? target.config.volatility,
        };
        emit(now, 'CONFIG_CHANGE', {
          machineId: change.machineId,
          title: `Paytable swap on ${change.machineId}`,
          description: `${change.machineId} swapped to ${change.newPaytableId} (theo hold ${change.newTheoreticalHoldPct.toFixed(1)}%).`,
          payload: {
            previous,
            paytable_id: change.newPaytableId,
            theoretical_hold_pct: change.newTheoreticalHoldPct,
            volatility: target.config.volatility,
          },
        });
      }
    }

    // Periodic machine status transitions: clear any expired faults, then
    // give faulty machines a chance to recover or escalate.
    for (const [machineId, machine] of machineStates) {
      if (machine.faultUntil !== null && now >= machine.faultUntil && machine.status !== 'IN_SERVICE') {
        machine.status = 'IN_SERVICE';
        machine.faultUntil = null;
        emit(now, 'MACHINE_STATUS', {
          machineId,
          title: 'Machine returned to service',
          description: `${machine.config.machineId} fault cleared by attendant.`,
          payload: { status: 'IN_SERVICE', previous_status: 'BILL_VALIDATOR_FAULT' },
        });
      } else if (
        machine.status === 'IN_SERVICE' &&
        machine.faultUntil !== null &&
        now >= machine.faultUntil - 30 &&
        machine.faultUntil > now
      ) {
        machine.status = 'BILL_VALIDATOR_FAULT';
        emit(now, 'MACHINE_STATUS', {
          machineId,
          title: 'Bill validator fault',
          description: `${machine.config.machineId} intermittently rejecting bills and vouchers.`,
          payload: { status: 'BILL_VALIDATOR_FAULT', expected_clear_at: machine.faultUntil },
        });
      } else if (
        machine.status === 'IN_SERVICE' &&
        scenario.faultRate > 0 &&
        rngFaults() < scenario.faultRate * TICK_SECONDS
      ) {
        machine.status = 'SOFT_FAULT';
        machine.faultUntil = now + 8 + rngFaults() * 12;
        emit(now, 'MACHINE_STATUS', {
          machineId,
          title: 'Soft fault on machine',
          description: `${machine.config.machineId} reported a transient soft fault.`,
          payload: { status: 'SOFT_FAULT', expected_clear_at: machine.faultUntil },
        });
      }
    }

    for (const patron of patrons) {
      tickPatron(patron, now, scenario, machineStates, progressivePool, rngOutcomes, emit);
    }

    // Sample positions at the configured cadence.
    if (now + 1e-6 >= nextSampleAt) {
      for (const patron of patrons) {
        if (patron.state === 'GONE' || patron.state === 'OFFSCREEN') continue;
        samples.push({
          simSecond: now,
          entityId: patron.id,
          entityType: 'patron',
          x: Number(patron.position.x.toFixed(2)),
          y: Number(patron.position.y.toFixed(2)),
          facing: patron.facing,
          activity: patronActivity(patron),
          status: null,
          targetId: patron.targetId,
          metadata: {
            color: patron.color,
            behavior: patron.behavior,
            label: patron.label,
            bankroll_cents: patron.bankrollCents,
            wallet_cents: patron.walletCents,
            preference_volatility: patron.preferenceVolatility,
            preference_denom_cents: patron.preferenceDenomCents,
          },
        });
      }
      nextSampleAt += SAMPLE_INTERVAL_SECONDS;
    }

    if (now + 1e-6 >= nextMeterPollAt) {
      for (const [machineId, machine] of machineStates) {
        meterPolls.push({
          simSecond: now,
          machineId,
          meters: { ...machine.meters },
        });
        emit(now, 'METER_POLL', {
          machineId,
          title: 'Meter poll',
          description: `${machineId} emitted an absolute meter snapshot.`,
          payload: { ...machine.meters },
        });
      }
      nextMeterPollAt += METER_POLL_INTERVAL_SECONDS;
    }
  }

  return { samples, events, meterPolls };
}

function tickPatron(
  patron: PatronState,
  now: number,
  scenario: ScenarioConfig,
  machines: Map<string, MachineRuntimeState>,
  progressivePool: ProgressivePool,
  rngOutcomes: () => number,
  emit: (
    simSecond: number,
    eventType: string,
    args: {
      patronId?: string | null;
      machineId?: string | null;
      title: string;
      description: string;
      payload?: Record<string, unknown>;
    },
  ) => void,
) {
  if (patron.state === 'GONE') return;
  if (patron.state === 'OFFSCREEN') {
    if (now < patron.arrivesAt) return;
    patron.state = 'WALKING_TO_SLOT';
    const slotTarget = pickInitialTarget(patron, machines);
    if (!slotTarget) {
      patron.state = patron.visitsBar ? 'WALKING_TO_BAR' : 'EXITING';
      patron.target = patron.visitsBar ? pickBarSeat(patron.id) : { ...patron.exitPoint };
      patron.targetId = patron.visitsBar ? 'bar-main' : null;
      patron.waypoints = buildWalkPath(
        patron.position,
        patron.target,
        'enter',
        patron.state === 'EXITING' ? 'exit' : 'none',
      );
    } else {
      patron.target = slotTarget;
      patron.waypoints = buildWalkPath(patron.position, slotTarget, 'enter', 'none');
    }
  }

  if (patron.state === 'WALKING_TO_SLOT' || patron.state === 'WALKING_TO_BAR' || patron.state === 'EXITING') {
    // Mid-walk fault response: if our destination slot has faulted, pick a
    // different machine (or fall back to bar/exit). Real-floor patrons notice
    // a "soft fault" attendant call from across the aisle and turn around.
    if (patron.state === 'WALKING_TO_SLOT' && patron.assignedMachineId) {
      const target = machines.get(patron.assignedMachineId);
      if (target && (target.status === 'BILL_VALIDATOR_FAULT' || target.status === 'OUT_OF_SERVICE' || target.status === 'DOOR_OPEN')) {
        if (target.occupantId === patron.id) target.occupantId = null;
        patron.assignedMachineId = null;
        const alt = pickInitialTarget(patron, machines);
        if (alt) {
          patron.target = alt;
          patron.targetId = patron.assignedMachineId;
          patron.waypoints = buildWalkPath(patron.position, alt, 'none', 'none');
        } else {
          patron.state = patron.visitsBar ? 'WALKING_TO_BAR' : 'EXITING';
          patron.target = patron.visitsBar ? pickBarSeat(patron.id) : { ...patron.exitPoint };
          patron.targetId = patron.visitsBar ? 'bar-main' : null;
          patron.waypoints = buildWalkPath(
            patron.position,
            patron.target,
            'none',
            patron.state === 'EXITING' ? 'exit' : 'none',
          );
        }
      }
    }

    // Consume waypoints one at a time so patrons follow the aisles.
    const nextWp = patron.waypoints[0] ?? patron.target;
    if (nextWp) {
      stepToward(patron, nextWp, TICK_SECONDS);
      if (distance(patron.position, nextWp) <= 0.3) {
        if (patron.waypoints.length > 0) {
          patron.waypoints.shift();
        }
      }
    }
    const reachedFinal =
      patron.target !== null && patron.waypoints.length === 0 && distance(patron.position, patron.target) <= 0.4;
    if (reachedFinal) {
      // Arrived
      if (patron.target) {
        if (patron.state === 'WALKING_TO_SLOT' && patron.assignedMachineId) {
          const machine = machines.get(patron.assignedMachineId);
          // pickInitialTarget soft-reserves the slot by setting occupantId
          // to this patron; treat that as still claimable on arrival.
          const claimable =
            machine && machine.status !== 'OUT_OF_SERVICE' &&
            (machine.occupantId === null || machine.occupantId === patron.id);
          if (machine && claimable) {
            machine.occupantId = patron.id;
            patron.state = 'PLAYING_SLOT';
            patron.sessionId = `session-${patron.id}-${Math.round(now)}`;
            patron.sessionStartedAt = now;
            patron.lastBetAt = now;
            patron.facing = 'north';
            // TITO cash-in: patron buys credits with cash from their wallet.
            // Typical bring-in is whatever they brought (capped to wallet) so
            // the bill_in meter captures the cash drop accurately.
            const cashInCents = Math.min(patron.walletCents, Math.max(500, Math.round(patron.bankrollCents * 0.5)));
            if (cashInCents > 0) {
              machine.meters.bill_in_cents += cashInCents;
              machine.creditCents += cashInCents;
              patron.walletCents -= cashInCents;
              emit(now, 'CASH_IN', {
                patronId: patron.id,
                machineId: machine.config.machineId,
                title: 'Cash-in',
                description: `${patron.id} inserted ${formatDollars(cashInCents)} at ${machine.config.machineId}.`,
                payload: {
                  session_id: patron.sessionId,
                  bill_in_delta_cents: cashInCents,
                  bill_denomination_mix: 'simulated',
                },
              });
            }
            emit(now, 'SESSION_START', {
              patronId: patron.id,
              machineId: machine.config.machineId,
              title: 'Session started',
              description: `${patron.id} sat down at ${machine.config.machineId} (${machine.config.theme}).`,
              payload: {
                session_id: patron.sessionId,
                theme: machine.config.theme,
                volatility: machine.config.volatility,
                denomination_cents: machine.config.denominationCents,
                paytable_id: machine.config.paytableId,
                theoretical_hold_pct: machine.config.theoreticalHoldPct,
                wallet_cents: patron.walletCents,
                credit_cents: machine.creditCents,
              },
            });
          } else {
            // Machine became unavailable while walking. Try to re-target.
            patron.assignedMachineId = null;
            patron.target = patron.visitsBar ? pickBarSeat(patron.id) : { ...patron.exitPoint };
            patron.targetId = patron.visitsBar ? 'bar-main' : null;
            patron.state = patron.visitsBar ? 'WALKING_TO_BAR' : 'EXITING';
            patron.waypoints = buildWalkPath(
              patron.position,
              patron.target,
              'none',
              patron.state === 'EXITING' ? 'exit' : 'none',
            );
          }
        } else if (patron.state === 'WALKING_TO_BAR') {
          patron.state = 'AT_BAR';
          patron.sessionStartedAt = now;
          patron.facing = 'north';
          emit(now, 'BAR_VISIT', {
            patronId: patron.id,
            title: 'Bar visit',
            description: `${patron.id} takes a break at the Neon Bar.`,
            payload: { wallet_cents: patron.walletCents },
          });
        } else if (patron.state === 'EXITING') {
          patron.state = 'GONE';
          patron.targetId = null;
        }
      }
    }
  } else if (patron.state === 'PLAYING_SLOT') {
    const machineId = patron.assignedMachineId;
    if (!machineId) {
      patron.state = patron.visitsBar && !patron.hasVisitedBar ? 'WALKING_TO_BAR' : 'EXITING';
      patron.target = patron.visitsBar && !patron.hasVisitedBar ? pickBarSeat(patron.id) : { ...patron.exitPoint };
      return;
    }
    const machine = machines.get(machineId);
    if (!machine) return;

    // If the machine faults, abandon after a couple of failed attempts.
    if (
      machine.status === 'BILL_VALIDATOR_FAULT' ||
      machine.status === 'DOOR_OPEN' ||
      machine.status === 'OUT_OF_SERVICE'
    ) {
      patron.faultsAbandoned += 1;
      endSession(patron, machine, now, emit, 'machine_fault');
      patron.state = patron.visitsBar && !patron.hasVisitedBar ? 'WALKING_TO_BAR' : 'EXITING';
      patron.target = patron.visitsBar && !patron.hasVisitedBar ? pickBarSeat(patron.id) : { ...patron.exitPoint };
      patron.targetId = patron.visitsBar && !patron.hasVisitedBar ? 'bar-main' : null;
      patron.waypoints = buildWalkPath(
        patron.position,
        patron.target,
        'none',
        patron.state === 'EXITING' ? 'exit' : 'none',
      );
      return;
    }

    if (now - patron.lastBetAt >= patron.betCadenceSeconds) {
      const denom = machine.config.denominationCents;
      const betUnits = Math.max(1, Math.floor(2 + rngOutcomes() * 5));
      const bet = denom * betUnits;
      // If credits are too low, try to re-buy from wallet (small CASH_IN);
      // failing that, walk the session out and ticket whatever's left.
      if (machine.creditCents < bet) {
        const rebuy = Math.min(patron.walletCents, Math.max(bet, 500));
        if (rebuy >= bet) {
          machine.meters.bill_in_cents += rebuy;
          machine.creditCents += rebuy;
          patron.walletCents -= rebuy;
          emit(now, 'CASH_IN', {
            patronId: patron.id,
            machineId: machine.config.machineId,
            title: 'Cash-in (rebuy)',
            description: `${patron.id} added ${formatDollars(rebuy)} mid-session at ${machine.config.machineId}.`,
            payload: {
              session_id: patron.sessionId,
              bill_in_delta_cents: rebuy,
              kind: 'rebuy',
            },
          });
        } else {
          endSession(patron, machine, now, emit, 'wallet_depleted');
          patron.state = patron.visitsBar && !patron.hasVisitedBar ? 'WALKING_TO_BAR' : 'EXITING';
          patron.target = patron.visitsBar && !patron.hasVisitedBar ? pickBarSeat(patron.id) : { ...patron.exitPoint };
          patron.targetId = patron.visitsBar && !patron.hasVisitedBar ? 'bar-main' : null;
          patron.waypoints = buildWalkPath(
            patron.position,
            patron.target,
            'none',
            patron.state === 'EXITING' ? 'exit' : 'none',
          );
          return;
        }
      }
      const outcome = resolveSpin(machine.config, bet, scenario, rngOutcomes);
      machine.meters.coin_in_cents += bet;
      machine.meters.coin_out_cents += outcome.winCents;
      machine.meters.progressive_contribution_cents += outcome.progressiveContributionCents;
      machine.meters.games_played += 1;
      machine.creditCents = machine.creditCents - bet + outcome.winCents;

      // Eligible spin contributes to the shared progressive pool.
      progressivePool.meterCents += outcome.progressiveContributionCents;

      // If the spin rolled a jackpot, the pool pays out and resets to seed.
      let jackpotCents = 0;
      if (outcome.jackpotHit) {
        jackpotCents = progressivePool.meterCents;
        progressivePool.meterCents = progressivePool.seedCents;
        machine.meters.jackpot_handpay_cents += jackpotCents;
        // Jackpot is hand-paid directly to the patron, bypassing credits.
        patron.walletCents += jackpotCents;
      }
      patron.lastBetAt = now;

      const isJackpot = jackpotCents > 0;
      emit(now, isJackpot ? 'JACKPOT_HANDPAY' : 'BET_SETTLED', {
        patronId: patron.id,
        machineId: machine.config.machineId,
        title: isJackpot
          ? `${formatDollars(jackpotCents)} progressive jackpot at ${machine.config.machineId}`
          : `Bet settled at ${machine.config.machineId}`,
        description: isJackpot
          ? `${patron.id} hits the progressive on ${machine.config.theme} — pool was ${formatDollars(jackpotCents)}; reset to seed.`
          : `${machine.config.machineId} records ${formatDollars(bet)} coin-in and ${formatDollars(outcome.winCents)} coin-out.`,
        payload: {
          session_id: patron.sessionId,
          bet_cents: bet,
          win_cents: outcome.winCents,
          jackpot_handpay_cents: jackpotCents,
          progressive_contribution_cents: outcome.progressiveContributionCents,
          coin_in_delta_cents: bet,
          coin_out_delta_cents: outcome.winCents,
          jackpot_handpay_delta_cents: jackpotCents,
          progressive_pool_after_cents: progressivePool.meterCents,
          theoretical_hold_pct: machine.config.theoreticalHoldPct,
          paytable_id: machine.config.paytableId,
          denomination_cents: denom,
          volatility: machine.config.volatility,
        },
      });
    }

    // Time/patience check: end after planned play seconds OR if patience runs out.
    const sessionElapsed = now - (patron.sessionStartedAt ?? now);
    if (sessionElapsed >= patron.sessionPlayPlannedSeconds || patron.walletCents <= 0) {
      endSession(patron, machine, now, emit, patron.walletCents <= 0 ? 'wallet_depleted' : 'planned_end');
      patron.state = patron.visitsBar && !patron.hasVisitedBar ? 'WALKING_TO_BAR' : 'EXITING';
      patron.target = patron.visitsBar && !patron.hasVisitedBar ? pickBarSeat(patron.id) : { ...patron.exitPoint };
      patron.targetId = patron.visitsBar && !patron.hasVisitedBar ? 'bar-main' : null;
      patron.waypoints = buildWalkPath(
        patron.position,
        patron.target,
        'none',
        patron.state === 'EXITING' ? 'exit' : 'none',
      );
    }
  } else if (patron.state === 'AT_BAR') {
    const barDwell = 10 + (patron.bankrollCents % 6) * 0.7;
    if (!patron.hasVisitedBar) patron.hasVisitedBar = true;
    if (now - (patron.sessionStartedAt ?? now) >= barDwell) {
      patron.state = 'EXITING';
      patron.target = { ...patron.exitPoint };
      patron.targetId = null;
      patron.waypoints = buildWalkPath(patron.position, patron.target, 'none', 'exit');
    }
  }
}

function endSession(
  patron: PatronState,
  machine: MachineRuntimeState,
  now: number,
  emit: (
    simSecond: number,
    eventType: string,
    args: {
      patronId?: string | null;
      machineId?: string | null;
      title: string;
      description: string;
      payload?: Record<string, unknown>;
    },
  ) => void,
  reason: string,
) {
  if (machine.occupantId === patron.id) machine.occupantId = null;
  // TITO ticket-out: any remaining credits print as a voucher, the patron
  // pockets the equivalent value, and the machine's voucher_out meter advances.
  const ticketCents = Math.max(0, machine.creditCents);
  if (ticketCents > 0) {
    machine.meters.voucher_out_cents += ticketCents;
    patron.walletCents += ticketCents;
    machine.creditCents = 0;
    emit(now, 'TICKET_OUT', {
      patronId: patron.id,
      machineId: machine.config.machineId,
      title: 'Ticket-out',
      description: `${machine.config.machineId} prints a ${formatDollars(ticketCents)} voucher for ${patron.id}.`,
      payload: {
        session_id: patron.sessionId,
        voucher_out_delta_cents: ticketCents,
      },
    });
  }
  emit(now, 'SESSION_END', {
    patronId: patron.id,
    machineId: machine.config.machineId,
    title: 'Session ended',
    description: `${patron.id} ended their session at ${machine.config.machineId} (${reason}).`,
    payload: {
      session_id: patron.sessionId,
      reason,
      wallet_cents: patron.walletCents,
      ticket_out_cents: ticketCents,
      duration_seconds: Number((now - (patron.sessionStartedAt ?? now)).toFixed(1)),
    },
  });
  patron.sessionId = null;
  patron.sessionStartedAt = null;
  patron.assignedMachineId = null;
  patron.targetId = null;
}

function resolveSpin(
  config: MachineConfig,
  bet: number,
  scenario: ScenarioConfig,
  rng: () => number,
) {
  const profile = VOLATILITY_PROFILES[config.volatility];
  let winCents = 0;
  const progressiveContributionCents = Math.max(1, Math.round(bet * 0.0125));

  if (rng() < profile.hitProb) {
    // Triangular-ish payout around avgMultiplierIfHit. Range [0.4, 1.6] has
    // mean 1.0 so the expected payout is exactly `avgMultiplierIfHit` and
    // long-run RTP lands on the configured value instead of overpaying ~10%.
    const multiplier = profile.avgMultiplierIfHit * (0.4 + rng() * 1.2);
    winCents = Math.round(bet * multiplier);
  }

  // Jackpot hit decision only — the payout amount is the shared pool meter,
  // resolved by the caller.
  const jackpotHit =
    profile.jackpotChance > 0 && rng() < profile.jackpotChance * scenario.jackpotMultiplier;

  return { winCents, jackpotHit, progressiveContributionCents };
}

function pickInitialTarget(
  patron: PatronState,
  machines: Map<string, MachineRuntimeState>,
): Point | null {
  // Prefer the patron's volatility/denom preferences when picking a machine.
  const candidates = Array.from(machines.values()).filter(
    (m) => m.status === 'IN_SERVICE' && m.occupantId === null,
  );
  if (candidates.length === 0) return null;
  const scored = candidates.map((m) => {
    let score = 0;
    if (patron.preferenceVolatility && m.config.volatility === patron.preferenceVolatility) score += 4;
    if (patron.preferenceDenomCents && m.config.denominationCents === patron.preferenceDenomCents) score += 2;
    score += Math.max(0, 8 - distance(patron.position, { x: m.config.x, y: m.config.y })) * 0.4;
    return { machine: m, score };
  });
  scored.sort((a, b) => b.score - a.score);
  const top = scored.slice(0, 4);
  const pick = top[Math.floor((patron.bankrollCents * 7) % top.length)] ?? top[0];
  if (!pick) return null;
  patron.assignedMachineId = pick.machine.config.machineId;
  patron.targetId = pick.machine.config.machineId;
  pick.machine.occupantId = patron.id; // soft reservation while walking
  // Stand right in front of the machine (south side).
  return { x: pick.machine.config.x + pick.machine.config.width / 2, y: pick.machine.config.y + pick.machine.config.height + 0.8 };
}

function stepToward(patron: PatronState, target: Point, dt: number) {
  const dx = target.x - patron.position.x;
  const dy = target.y - patron.position.y;
  const d = Math.hypot(dx, dy);
  if (d < 1e-3) return;
  const step = Math.min(d, WALK_SPEED_TILES_PER_SECOND * dt);
  const nx = patron.position.x + (dx / d) * step;
  const ny = patron.position.y + (dy / d) * step;
  patron.position = { x: nx, y: ny };
  patron.facing = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'east' : 'west') : dy > 0 ? 'south' : 'north';
}

function distance(a: Point, b: Point) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function patronActivity(patron: PatronState) {
  switch (patron.state) {
    case 'WALKING_TO_SLOT':
    case 'WALKING_TO_BAR':
      return 'WALKING';
    case 'PLAYING_SLOT':
      return 'PLAYING_SLOT';
    case 'AT_BAR':
      return 'AT_BAR';
    case 'EXITING':
      return 'EXITING';
    case 'WAITING':
      return 'WAITING';
    default:
      return 'WALKING';
  }
}

function buildPatron(index: number, scenario: ScenarioConfig, rng: () => number): PatronState {
  const id = `patron-${(index + 1).toString().padStart(3, '0')}`;
  const colors = ['#40d1f5', '#f5b940', '#eb1600', '#a78bfa', '#34d399', '#fb7185', '#60a5fa', '#facc15', '#f97316', '#22d3ee'];
  const archetypeRoll = rng();
  let label = 'Casual Player';
  let behavior = 'casual';
  let bankrollCents = 4_000;
  let preferenceVolatility: Volatility | null = null;
  let preferenceDenomCents: number | null = null;
  let visitsBar = false;
  const patienceSeconds = 60;
  // Faster bet cadence + longer sessions than the original tick-driven defaults
  // so each machine accumulates enough coin-in for actual/theoretical hold to
  // converge over a 10-minute run (the demo's standard duration).
  let betCadenceSeconds = 2.0;
  let sessionPlayPlannedSeconds = 90 + rng() * 90;

  if (archetypeRoll < 0.18) {
    label = 'High Roller';
    behavior = 'high_roller';
    bankrollCents = 28_000 + Math.floor(rng() * 22_000);
    preferenceVolatility = 'HIGH';
    preferenceDenomCents = 100;
    betCadenceSeconds = 2.5;
    sessionPlayPlannedSeconds = 180 + rng() * 120;
  } else if (archetypeRoll < 0.36) {
    label = 'Jackpot Chaser';
    behavior = 'jackpot_chaser';
    bankrollCents = 6_500 + Math.floor(rng() * 4_500);
    preferenceVolatility = 'HIGH';
    betCadenceSeconds = 1.8;
    sessionPlayPlannedSeconds = 120 + rng() * 90;
  } else if (archetypeRoll < 0.6) {
    label = 'Grinder';
    behavior = 'grinder';
    bankrollCents = 5_500 + Math.floor(rng() * 3_500);
    preferenceVolatility = 'LOW';
    preferenceDenomCents = 25;
    betCadenceSeconds = 1.6;
    sessionPlayPlannedSeconds = 150 + rng() * 120;
  } else if (archetypeRoll < 0.75) {
    label = 'Bar Hopper';
    behavior = 'bar_hopper';
    bankrollCents = 3_000 + Math.floor(rng() * 2_000);
    visitsBar = true;
    sessionPlayPlannedSeconds = 35 + rng() * 30;
  } else if (archetypeRoll < 0.88) {
    label = 'Window Shopper';
    behavior = 'window_shopper';
    bankrollCents = 2_500 + Math.floor(rng() * 1_500);
    sessionPlayPlannedSeconds = 30 + rng() * 35;
  } else {
    label = 'Pass Through';
    behavior = 'pass_through';
    bankrollCents = 0;
    sessionPlayPlannedSeconds = 0;
  }
  if (rng() < 0.18) visitsBar = true;

  const spawn = ENTRANCES[Math.floor(rng() * ENTRANCES.length)];
  // Per-patron jitter so multiple patrons sharing an entrance don't stack.
  const jitterX = (rng() - 0.5) * 1.6;
  const jitterY = (rng() - 0.5) * 1.6;
  const spawnPoint = { x: spawn.x + jitterX, y: spawn.y + jitterY };
  const exitIdx = Math.floor(rng() * ENTRANCES.length);
  const exitBase = ENTRANCES[exitIdx];
  const exitPoint = {
    x: exitBase.x + (rng() - 0.5) * 1.6,
    y: exitBase.y + (rng() - 0.5) * 1.6,
  };
  const arrivesAt = Number((-10 + index * scenario.arrivalIntervalSeconds + (rng() - 0.5) * 0.6).toFixed(2));

  return {
    id,
    color: colors[index % colors.length],
    label,
    behavior,
    bankrollCents,
    walletCents: bankrollCents,
    preferenceVolatility,
    preferenceDenomCents,
    visitsBar,
    patienceSeconds,
    betCadenceSeconds,
    arrivesAt,
    spawnPoint,
    exitPoint,
    position: { ...spawnPoint },
    facing: 'south',
    state: 'OFFSCREEN',
    target: null,
    targetId: null,
    waypoints: [],
    assignedMachineId: null,
    sessionId: null,
    sessionStartedAt: null,
    sessionPlayPlannedSeconds,
    lastBetAt: 0,
    hasVisitedBar: false,
    faultsAbandoned: 0,
  };
}

function mulberry32(seed: number) {
  let t = seed >>> 0;
  return function rng() {
    t = (t + 0x6d2b79f5) >>> 0;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function formatDollars(cents: number) {
  return `$${(cents / 100).toFixed(2)}`;
}
