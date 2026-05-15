# Bill validator fault — troubleshooting

`BILL_VALIDATOR_FAULT` is the most common cabinet-side fault we see on
the floor. The validator is the cash/voucher acceptor — a fault means
the machine intermittently rejects bills or vouchers and patrons
abandon their session.

## Symptoms

- Status events: `MACHINE_STATUS` with `status: "BILL_VALIDATOR_FAULT"`.
- Behavior: sessions on this machine end early; patrons often switch to
  a neighbor in the same bank within ~30 simulated seconds.
- Meters: `bill_in_cents` and `voucher_in_cents` deltas drop to near zero
  while the fault is active; `coin_in_cents` may continue briefly if the
  patron is playing down existing credits.

## Triage flow

1. **Confirm the fault is real.** Look at the last `MACHINE_STATUS`
   event payload for `expected_clear_at`. If the timestamp is in the
   future, the machine has self-flagged and an attendant is being
   dispatched.
2. **Decide whether to escalate.** Soft faults (`SOFT_FAULT`) usually
   clear in 8–20 simulated seconds and need no attendant action. Hard
   faults (`BILL_VALIDATOR_FAULT`, `DOOR_OPEN`) require an attendant.
3. **Suspend the session.** Mark the active session as ended in the
   accounting system (the simulator does this automatically). Verify a
   matching `SESSION_END` event was emitted.
4. **Service the validator.** Common causes:
   - Lint or torn-bill buildup at the intake roller.
   - Bill-stacker full or jammed.
   - Sensor calibration drift after temperature swing.
5. **Return to service.** Manually emit (or wait for the simulator to
   emit) a `MACHINE_STATUS` event with `status: "IN_SERVICE"` and
   `previous_status: "BILL_VALIDATOR_FAULT"` so analytics knows the
   downtime ended.

## Time-to-resolve targets

| Severity | Target TTR |
| --- | --- |
| Soft fault (auto-clear) | <20 s |
| Bill validator fault | <90 s |
| Door open | <60 s |
| Out of service (escalated) | <10 min |

## Why this matters analytically

When a machine is faulted, traffic shifts to neighbors. In the
`silver_slot_spins` table you'll see a temporary dip in `coin_in_cents`
for the faulted machine and a corresponding bump in the adjacent
machines' coin-in. If hold on the affected bank drifts during this
window, **don't chase the bank-level hold gap** — the cause is the
fault, not the configuration.

## Educational disclaimer

This procedure is illustrative. Real-world maintenance protocols are
jurisdiction-specific (see Nevada Reg 14 §14.040, UKGC RTS 9).
