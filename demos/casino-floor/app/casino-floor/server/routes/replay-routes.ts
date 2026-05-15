import { Application } from 'express';
import {
  MachineConfig,
  ScenarioConfig,
  simulate,
} from '../simulation/casino-simulator';

interface AppKitWithLakebase {
  lakebase: {
    query(text: string, params?: unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
  };
  server: {
    extend(fn: (app: Application) => void): void;
  };
}

// Two Postgres schemas:
//   app     — accounting-relevant tables that Lakehouse Sync replicates to Delta
//   replay  — high-volume visual-only data (replay_samples) that stays Lakebase-only
const SCHEMA_SQL = [
  `CREATE SCHEMA IF NOT EXISTS app`,
  `CREATE SCHEMA IF NOT EXISTS replay`,
  // One-shot cleanup: replay_samples used to live in `app`. After moving it to
  // schema `replay` so Lakehouse Sync doesn't ship 60k visual-only rows to
  // Delta, drop the legacy table if it's hanging around.
  `DROP TABLE IF EXISTS app.replay_samples CASCADE`,
];

const TABLE_SQL = [
  `CREATE TABLE IF NOT EXISTS app.simulation_runs (
    run_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    duration_seconds INTEGER NOT NULL,
    sample_rate_hz NUMERIC NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  )`,
  `CREATE TABLE IF NOT EXISTS app.floor_entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    label TEXT NOT NULL,
    x NUMERIC NOT NULL,
    y NUMERIC NOT NULL,
    width NUMERIC NOT NULL,
    height NUMERIC NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
  )`,
  `CREATE TABLE IF NOT EXISTS replay.replay_samples (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES app.simulation_runs(run_id),
    sim_second NUMERIC NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    x NUMERIC NOT NULL,
    y NUMERIC NOT NULL,
    facing TEXT NOT NULL,
    activity TEXT NOT NULL,
    status TEXT,
    target_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
  )`,
  `CREATE TABLE IF NOT EXISTS app.activity_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES app.simulation_runs(run_id),
    sim_second NUMERIC NOT NULL,
    event_type TEXT NOT NULL,
    entity_id TEXT,
    patron_id TEXT,
    machine_id TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
  )`,
  `CREATE TABLE IF NOT EXISTS app.meter_polls (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES app.simulation_runs(run_id),
    sim_second NUMERIC NOT NULL,
    machine_id TEXT NOT NULL,
    meters JSONB NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS replay_samples_run_time_idx
    ON replay.replay_samples (run_id, sim_second)`,
  `CREATE INDEX IF NOT EXISTS activity_events_run_time_idx
    ON app.activity_events (run_id, sim_second)`,
  // Lakehouse Sync requires REPLICA IDENTITY FULL on every source table so
  // the WAL captures complete row state for downstream Delta. We skip
  // replay_samples — it's high-volume and visual-only, not part of the
  // analytics surface. The other four are the accounting-relevant tables
  // that flow to Unity Catalog via wal2delta.
  `ALTER TABLE app.simulation_runs REPLICA IDENTITY FULL`,
  `ALTER TABLE app.floor_entities REPLICA IDENTITY FULL`,
  `ALTER TABLE app.activity_events REPLICA IDENTITY FULL`,
  `ALTER TABLE app.meter_polls REPLICA IDENTITY FULL`,
];

interface ScenarioPreset {
  runId: string;
  name: string;
  description: string;
  scenario: ScenarioConfig;
}

const SCENARIOS: ScenarioPreset[] = [
  {
    runId: 'demo-run-001',
    name: 'Opening Night',
    description: 'Standard floor: 130 patrons over 10 minutes, real bet outcomes, meter polls, one bill-validator fault window, occasional high-volatility jackpots.',
    scenario: {
      durationSeconds: 600,
      patronCount: 130,
      arrivalIntervalSeconds: 4.5,
      seed: 0x57c1a01a,
      faultRate: 0.0005,
      jackpotMultiplier: 1,
      barAttractiveness: 1,
    },
  },
  {
    runId: 'demo-run-002-quiet',
    name: 'Quiet Wednesday',
    description: 'Light traffic: 70 patrons over 10 minutes. Use this to show what hold variance looks like at low coin-in volume.',
    scenario: {
      durationSeconds: 600,
      patronCount: 70,
      arrivalIntervalSeconds: 8.5,
      seed: 0x1c0b2a91,
      faultRate: 0.0003,
      jackpotMultiplier: 1,
      barAttractiveness: 0.6,
    },
  },
  {
    runId: 'demo-run-003-jackpot',
    name: 'Jackpot Storm',
    description: 'High-volatility heavy: jackpot multiplier 3x. Shows how a jackpot hand-pay distorts hold even though the machine is configured normally.',
    scenario: {
      durationSeconds: 600,
      patronCount: 130,
      arrivalIntervalSeconds: 4.5,
      seed: 0x4ea7c331,
      faultRate: 0.0005,
      jackpotMultiplier: 3,
      barAttractiveness: 1,
    },
  },
  {
    runId: 'demo-run-004-faults',
    name: 'Fault-Heavy Shift',
    description: 'Faulty bank scenario: bill validator faults and soft faults clustered. Watch session abandonment and traffic shift to neighboring machines.',
    scenario: {
      durationSeconds: 600,
      patronCount: 130,
      arrivalIntervalSeconds: 4.5,
      seed: 0x9933cb71,
      faultRate: 0.0035,
      jackpotMultiplier: 1,
      barAttractiveness: 1,
    },
  },
  {
    runId: 'demo-run-005-config-change',
    name: 'Paytable Update Mid-Shift',
    description: 'At sim_t=240s slot-005 swaps from PAR-925 to PAR-905 (theo hold 5.4% → 9.5%). Compare pre/post-change hold to see why segmenting by paytable_id matters.',
    scenario: {
      durationSeconds: 720,
      patronCount: 130,
      arrivalIntervalSeconds: 5.4,
      seed: 0xa4d7c102,
      faultRate: 0.0005,
      jackpotMultiplier: 1,
      barAttractiveness: 1,
      configChanges: [
        {
          atSimSecond: 240,
          machineId: 'slot-005',
          newPaytableId: 'PAR-SLOT-005-905',
          newTheoreticalHoldPct: 9.5,
          newVolatility: 'HIGH',
        },
      ],
    },
  },
];

type JsonRecord = Record<string, unknown>;

interface FloorEntity {
  entity_id: string;
  entity_type: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  metadata: JsonRecord;
}

interface ReplaySample {
  run_id: string;
  sim_second: number;
  entity_id: string;
  entity_type: string;
  x: number;
  y: number;
  facing: string;
  activity: string;
  status: string | null;
  target_id: string | null;
  metadata: JsonRecord;
}

interface ActivityEvent {
  event_id: string;
  run_id: string;
  sim_second: number;
  event_type: string;
  entity_id: string | null;
  patron_id: string | null;
  machine_id: string | null;
  title: string;
  description: string;
  payload: JsonRecord;
}

interface MeterPoll {
  run_id: string;
  sim_second: number;
  machine_id: string;
  meters: JsonRecord;
}

export async function setupCasinoReplayRoutes(appkit: AppKitWithLakebase) {
  try {
    for (const statement of SCHEMA_SQL) {
      try {
        await appkit.lakebase.query(statement);
      } catch (err) {
        console.warn('[casino-floor] Non-fatal schema statement failed:', (err as Error).message);
      }
    }
    for (const statement of TABLE_SQL) {
      try {
        await appkit.lakebase.query(statement);
      } catch (err) {
        console.warn('[casino-floor] Non-fatal table statement failed:', (err as Error).message);
      }
    }
    // Only seed missing runs (or all, if FORCE_RESEED=1) so Lakebase acts as
    // the durable store rather than a per-process cache.
    const forceReseed = process.env.FORCE_RESEED === '1';
    for (const preset of SCENARIOS) {
      const existing = await appkit.lakebase.query(
        'SELECT 1 FROM app.simulation_runs WHERE run_id = $1 LIMIT 1',
        [preset.runId],
      );
      if (forceReseed || existing.rows.length === 0) {
        await seedScenario(appkit, preset);
        console.log(`[casino-floor] Seeded scenario ${preset.runId} ${forceReseed ? '(forced)' : '(initial)'}`);
      } else {
        console.log(`[casino-floor] Scenario ${preset.runId} already seeded; skipping`);
      }
    }
    console.log('[casino-floor] Replay schema ready');
  } catch (err) {
    console.warn('[casino-floor] Replay schema setup failed:', (err as Error).message);
    console.warn('[casino-floor] API routes will still be registered but may return errors');
  }

  appkit.server.extend((app) => {
    app.get('/api/replay/runs', async (_req, res) => {
      try {
        const result = await appkit.lakebase.query(
          `SELECT run_id, name, description, starts_at, duration_seconds, sample_rate_hz
           FROM app.simulation_runs
           ORDER BY starts_at DESC`,
        );
        res.json(result.rows);
      } catch (err) {
        console.error('Failed to list replay runs:', err);
        res.status(500).json({ error: 'Failed to list replay runs' });
      }
    });

    app.get('/api/replay/runs/:runId', async (req, res) => {
      try {
        const runId = req.params.runId;
        const [run, entities, samples, events, meters] = await Promise.all([
          appkit.lakebase.query(
            `SELECT run_id, name, description, starts_at, duration_seconds, sample_rate_hz
             FROM app.simulation_runs
             WHERE run_id = $1`,
            [runId],
          ),
          appkit.lakebase.query(
            `SELECT entity_id, entity_type, label, x, y, width, height, metadata
             FROM app.floor_entities
             ORDER BY entity_type, entity_id`,
          ),
          appkit.lakebase.query(
            `SELECT sim_second, entity_id, entity_type, x, y, facing, activity, status, target_id, metadata
             FROM replay.replay_samples
             WHERE run_id = $1
             ORDER BY sim_second, entity_id`,
            [runId],
          ),
          appkit.lakebase.query(
            `SELECT event_id, sim_second, event_type, entity_id, patron_id, machine_id, title, description, payload
             FROM app.activity_events
             WHERE run_id = $1
             ORDER BY sim_second, event_id`,
            [runId],
          ),
          appkit.lakebase.query(
            `SELECT sim_second, machine_id, meters
             FROM app.meter_polls
             WHERE run_id = $1
             ORDER BY sim_second, machine_id`,
            [runId],
          ),
        ]);

        if (run.rows.length === 0) {
          res.status(404).json({ error: 'Replay run not found' });
          return;
        }

        res.json({
          run: run.rows[0],
          entities: entities.rows,
          samples: samples.rows,
          events: events.rows,
          meter_polls: meters.rows,
        });
      } catch (err) {
        console.error('Failed to load replay run:', err);
        res.status(500).json({ error: 'Failed to load replay run' });
      }
    });
  });
}

async function seedScenario(appkit: AppKitWithLakebase, preset: ScenarioPreset) {
  const runId = preset.runId;
  const entities = buildFloorEntities();
  const machineConfigs: MachineConfig[] = entities
    .filter((entity) => entity.entity_type === 'machine')
    .map((entity) => {
      const meta = entity.metadata as Record<string, unknown>;
      const volatility = (meta.volatility as 'LOW' | 'MEDIUM' | 'HIGH' | undefined) ?? 'MEDIUM';
      return {
        machineId: entity.entity_id,
        bankId: typeof meta.bank_id === 'string' ? meta.bank_id : 'bank-unknown',
        x: entity.x,
        y: entity.y,
        width: entity.width,
        height: entity.height,
        theme: typeof meta.theme === 'string' ? meta.theme : 'Neon Buffalo',
        paytableId: `PAR-${entity.entity_id.toUpperCase()}-${volatility === 'LOW' ? '946' : volatility === 'HIGH' ? '905' : '925'}`,
        denominationCents: typeof meta.denomination_cents === 'number' ? meta.denomination_cents : 25,
        volatility,
        theoreticalHoldPct: volatility === 'LOW' ? 5.4 : volatility === 'HIGH' ? 9.5 : 7.5,
      };
    });

  const result = simulate(preset.scenario, machineConfigs);

  const samples: ReplaySample[] = result.samples.map((row) => ({
    run_id: runId,
    sim_second: row.simSecond,
    entity_id: row.entityId,
    entity_type: row.entityType,
    x: row.x,
    y: row.y,
    facing: row.facing,
    activity: row.activity,
    status: row.status,
    target_id: row.targetId,
    metadata: row.metadata,
  }));
  const events: ActivityEvent[] = result.events.map((row) => ({
    event_id: `${runId}-${row.eventId}`,
    run_id: runId,
    sim_second: row.simSecond,
    event_type: row.eventType,
    entity_id: row.entityId,
    patron_id: row.patronId,
    machine_id: row.machineId,
    title: row.title,
    description: row.description,
    payload: row.payload,
  }));
  const meterPolls: MeterPoll[] = result.meterPolls.map((row) => ({
    run_id: runId,
    sim_second: row.simSecond,
    machine_id: row.machineId,
    meters: row.meters as JsonRecord,
  }));

  await appkit.lakebase.query('DELETE FROM app.meter_polls WHERE run_id = $1', [runId]);
  await appkit.lakebase.query('DELETE FROM app.activity_events WHERE run_id = $1', [runId]);
  await appkit.lakebase.query('DELETE FROM replay.replay_samples WHERE run_id = $1', [runId]);

  await appkit.lakebase.query(
    `INSERT INTO app.simulation_runs
      (run_id, name, description, starts_at, duration_seconds, sample_rate_hz)
     VALUES ($1, $2, $3, $4, $5, $6)
     ON CONFLICT (run_id) DO UPDATE SET
       name = EXCLUDED.name,
       description = EXCLUDED.description,
       starts_at = EXCLUDED.starts_at,
       duration_seconds = EXCLUDED.duration_seconds,
       sample_rate_hz = EXCLUDED.sample_rate_hz`,
    [
      runId,
      preset.name,
      preset.description,
      '2026-05-13T20:00:00Z',
      preset.scenario.durationSeconds,
      2,
    ],
  );

  for (const entity of entities) {
    await appkit.lakebase.query(
      `INSERT INTO app.floor_entities
        (entity_id, entity_type, label, x, y, width, height, metadata)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
       ON CONFLICT (entity_id) DO UPDATE SET
         entity_type = EXCLUDED.entity_type,
         label = EXCLUDED.label,
         x = EXCLUDED.x,
         y = EXCLUDED.y,
         width = EXCLUDED.width,
         height = EXCLUDED.height,
         metadata = EXCLUDED.metadata`,
      [
        entity.entity_id,
        entity.entity_type,
        entity.label,
        entity.x,
        entity.y,
        entity.width,
        entity.height,
        JSON.stringify(entity.metadata),
      ],
    );
  }

  await insertReplaySamples(appkit, samples);

  for (const event of events) {
    await appkit.lakebase.query(
      `INSERT INTO app.activity_events
        (event_id, run_id, sim_second, event_type, entity_id, patron_id, machine_id, title, description, payload)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
       ON CONFLICT (event_id) DO UPDATE SET
         sim_second = EXCLUDED.sim_second,
         event_type = EXCLUDED.event_type,
         entity_id = EXCLUDED.entity_id,
         patron_id = EXCLUDED.patron_id,
         machine_id = EXCLUDED.machine_id,
         title = EXCLUDED.title,
         description = EXCLUDED.description,
         payload = EXCLUDED.payload`,
      [
        event.event_id,
        event.run_id,
        event.sim_second,
        event.event_type,
        event.entity_id,
        event.patron_id,
        event.machine_id,
        event.title,
        event.description,
        JSON.stringify(event.payload),
      ],
    );
  }

  for (const poll of meterPolls) {
    await appkit.lakebase.query(
      `INSERT INTO app.meter_polls
        (run_id, sim_second, machine_id, meters)
       VALUES ($1, $2, $3, $4::jsonb)`,
      [poll.run_id, poll.sim_second, poll.machine_id, JSON.stringify(poll.meters)],
    );
  }
}

async function insertReplaySamples(appkit: AppKitWithLakebase, samples: ReplaySample[]) {
  const columnsPerRow = 11;
  const chunkSize = 500;

  for (let index = 0; index < samples.length; index += chunkSize) {
    const chunk = samples.slice(index, index + chunkSize);
    const values: unknown[] = [];
    const placeholders = chunk.map((sample, rowIndex) => {
      values.push(
        sample.run_id,
        sample.sim_second,
        sample.entity_id,
        sample.entity_type,
        sample.x,
        sample.y,
        sample.facing,
        sample.activity,
        sample.status,
        sample.target_id,
        JSON.stringify(sample.metadata),
      );
      const offset = rowIndex * columnsPerRow;
      return `($${offset + 1}, $${offset + 2}, $${offset + 3}, $${offset + 4}, $${offset + 5}, $${offset + 6}, $${offset + 7}, $${offset + 8}, $${offset + 9}, $${offset + 10}, $${offset + 11}::jsonb)`;
    });

    await appkit.lakebase.query(
      `INSERT INTO replay.replay_samples
        (run_id, sim_second, entity_id, entity_type, x, y, facing, activity, status, target_id, metadata)
       VALUES ${placeholders.join(', ')}`,
      values,
    );
  }
}

function buildFloorEntities(): FloorEntity[] {
  const entities: FloorEntity[] = [
    {
      entity_id: 'entrance-main',
      entity_type: 'entrance',
      label: 'Main Entrance',
      x: 2,
      y: 16,
      width: 3,
      height: 1,
      metadata: {},
    },
    {
      entity_id: 'bar-main',
      entity_type: 'bar',
      label: 'Neon Bar',
      x: 20,
      y: 3,
      width: 6,
      height: 5,
      metadata: { seats: 8 },
    },
  ];

  const banks = [
    { bank: 'A', x: 5.3, y: 4 },
    { bank: 'B', x: 5.3, y: 10 },
    { bank: 'C', x: 14.2, y: 4 },
    { bank: 'D', x: 14.2, y: 10 },
  ];

  let index = 1;
  for (const bank of banks) {
    for (let offset = 0; offset < 5; offset += 1) {
      const machineId = `slot-${index.toString().padStart(3, '0')}`;
      entities.push({
        entity_id: machineId,
        entity_type: 'machine',
        label: `Slot ${index.toString().padStart(3, '0')}`,
        x: Number((bank.x + offset * 1.25).toFixed(2)),
        y: bank.y,
        width: 1.05,
        height: 1.05,
        metadata: {
          bank_id: `bank-${bank.bank.toLowerCase()}`,
          denomination_cents: offset % 2 === 0 ? 25 : 100,
          volatility: ['LOW', 'MEDIUM', 'HIGH'][offset % 3],
          theme: ['Neon Buffalo', 'Lucky Lanterns', 'Moonlight 7s'][offset % 3],
        },
      });
      index += 1;
    }
  }

  return entities;
}

