export interface ReplayRun {
  run_id: string;
  name: string;
  description: string;
  starts_at: string;
  duration_seconds: number | string;
  sample_rate_hz: number | string;
}

export interface FloorEntity {
  entity_id: string;
  entity_type: 'machine' | 'bar' | 'entrance';
  label: string;
  x: number | string;
  y: number | string;
  width: number | string;
  height: number | string;
  metadata: Record<string, unknown>;
}

export interface ReplaySample {
  sim_second: number | string;
  entity_id: string;
  entity_type: 'patron';
  x: number | string;
  y: number | string;
  facing: string;
  activity: string;
  status: string | null;
  target_id: string | null;
  metadata: Record<string, unknown>;
}

export interface ActivityEvent {
  event_id: string;
  sim_second: number | string;
  event_type: string;
  entity_id: string | null;
  patron_id: string | null;
  machine_id: string | null;
  title: string;
  description: string;
  payload: Record<string, unknown>;
}

export interface MeterPoll {
  sim_second: number | string;
  machine_id: string;
  meters: Record<string, number | string>;
}

export interface ReplayPayload {
  run: ReplayRun;
  entities: FloorEntity[];
  samples: ReplaySample[];
  events: ActivityEvent[];
  meter_polls: MeterPoll[];
}
