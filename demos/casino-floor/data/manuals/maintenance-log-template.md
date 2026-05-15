# Maintenance log entry — template

A maintenance log entry is filled out by an attendant or shift
supervisor every time a machine transitions to a non-`IN_SERVICE`
status. In the demo, these entries are stand-ins for what would be
filed in a real OSMS (online slot management system).

## Fields

| Field | Description |
| --- | --- |
| `entry_id` | Monotonic ID, e.g. `MAINT-2026-05-13-0042`. |
| `machine_id` | Slot id, e.g. `slot-008`. |
| `bank_id` | Bank for grouping (`bank-a`, `bank-b`, ...). |
| `opened_at_ts` | Wall-clock time the entry was opened. |
| `opened_at_sim_second` | Simulated time on the active run, for replay alignment. |
| `severity` | `SOFT_FAULT`, `BILL_VALIDATOR_FAULT`, `DOOR_OPEN`, `OUT_OF_SERVICE`. |
| `attendant_id` | Who was dispatched (synthetic id only — no PII). |
| `description` | Free-text reason. Keep under 280 chars. |
| `actions_taken` | Multi-line. What the attendant did. |
| `closed_at_sim_second` | Simulated time the machine returned to service. |
| `time_to_resolve_seconds` | `closed_at_sim_second - opened_at_sim_second`. |
| `root_cause` | One of `mechanical`, `electrical`, `software`, `bill_handling`, `door_security`, `customer_caused`, `unknown`. |
| `closed_by` | Attendant or shift supervisor id. |

## Severity classification

- **SOFT_FAULT** — transient sensor error. Auto-clear in <20 s. No
  attendant required. Logged for trend analysis only.
- **BILL_VALIDATOR_FAULT** — see [bill-validator-troubleshooting.md].
  Attendant dispatched. Target TTR: <90 s.
- **DOOR_OPEN** — cabinet door opened (legitimate service or
  tampering). Attendant required to verify and reseat. Target TTR: <60 s.
- **OUT_OF_SERVICE** — manual flag set by an attendant; machine is
  unplayable until cleared. Used for extended service. No TTR target.

## Example entry

```
entry_id: MAINT-2026-05-13-0042
machine_id: slot-008
bank_id: bank-b
opened_at_sim_second: 40.0
severity: BILL_VALIDATOR_FAULT
attendant_id: attendant-014
description: Intermittent voucher rejects after patron-058 attempted cash-in.
actions_taken: |
  - Removed two stuck vouchers from intake roller
  - Wiped sensor and recalibrated bill path
  - Tested cash-in with sample voucher; OK on third attempt
closed_at_sim_second: 70.0
time_to_resolve_seconds: 30.0
root_cause: bill_handling
closed_by: supervisor-002
```

## Why this matters analytically

Maintenance log entries are the "why" behind every `MACHINE_STATUS`
event. When `gold_anomaly_candidates` flags `FAULT_RATE_SPIKE` for a
bank, the maintenance corpus is what a Knowledge Assistant should be
able to surface — the root-cause distribution explains whether the
spike is a bank-wide hardware issue, a patron-caused pattern, or
software drift.
