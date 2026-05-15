#!/usr/bin/env bash
# Run the Genie starter queries against one scenario's exported JSONL.
# Used to verify the SQL works end-to-end before any Delta plumbing exists.
#
# usage: ./scripts/run-genie-queries.sh [run_id]    (default: demo-run-001)

set -euo pipefail

RUN_ID="${1:-demo-run-001}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXPORT_DIR="$ROOT/data/exports/$RUN_ID"
QUERIES="$ROOT/docs/genie-starter-queries.sql"

if [ ! -d "$EXPORT_DIR" ]; then
  echo "no exports for $RUN_ID — run: cd app/casino-floor && npm run export -- $RUN_ID" >&2
  exit 2
fi

# Register each JSONL file as a view, then run the starter queries.
duckdb <<SQL
CREATE VIEW bronze_slot_events      AS SELECT * FROM read_json_auto('$EXPORT_DIR/bronze_slot_events.jsonl');
CREATE VIEW silver_slot_spins        AS SELECT * FROM read_json_auto('$EXPORT_DIR/silver_slot_spins.jsonl');
CREATE VIEW silver_meter_polls       AS SELECT * FROM read_json_auto('$EXPORT_DIR/silver_meter_polls.jsonl');
CREATE VIEW silver_machine_status    AS SELECT * FROM read_json_auto('$EXPORT_DIR/silver_machine_status.jsonl');
CREATE VIEW silver_patron_sessions   AS SELECT * FROM read_json_auto('$EXPORT_DIR/silver_patron_sessions.jsonl');
CREATE VIEW gold_machine_daily       AS SELECT * FROM read_json_auto('$EXPORT_DIR/gold_machine_daily.jsonl');
CREATE VIEW gold_progressive_summary AS SELECT * FROM read_json_auto('$EXPORT_DIR/gold_progressive_summary.jsonl');

.mode line
$(cat "$QUERIES")
SQL
