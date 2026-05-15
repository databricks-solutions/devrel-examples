# Floor narratives — anomaly playbook

The demo seeds six recognizable anomaly narratives. Each narrative is
designed to look interesting at first glance and have a credible
data-grounded explanation an operator (or eventually Genie) can
articulate.

## 1. Normal variance misread as a problem

**Setup:** A high-volatility machine has a short cold streak and
appears to hold far above PAR.

**Signal:**
- High `hold_variance_bps`.
- Low `coin_in_cents` for the period (under ~$2k).
- No `MACHINE_STATUS` events for the machine.
- No `CONFIG_CHANGE` events for the machine.

**Operator answer:** "Coin-in is too low to conclude drift. Wait until
the machine has accumulated ~$5k of post-reset coin-in or pool with
sibling machines by `paytable_id` before flagging."

## 2. Jackpot-adjusted hold

**Setup:** A progressive jackpot hits in one bank and actual hold
collapses for the period.

**Signal:**
- Recent `JACKPOT_HANDPAY` event with a large
  `jackpot_handpay_delta_cents`.
- Bank-level `actual_hold_pct` deeply negative.
- `jackpot_adjusted_hold_pct` near theoretical.

**Operator answer:** "The negative hold is the hand-pay. Ex-jackpot
hold is within range. Hold the analysis until the meter has
re-accumulated."

## 3. Bill validator fault

**Setup:** One machine intermittently rejects bills or vouchers.
Patrons abandon it more quickly, session count drops, and adjacent
machines pick up traffic.

**Signal:**
- `MACHINE_STATUS` event with `status: "BILL_VALIDATOR_FAULT"`.
- Lower uptime for the machine in `silver_machine_status`.
- Shorter `silver_patron_sessions` durations on the affected machine.
- Lower `bill_in_cents` and `voucher_in_cents` meter deltas.
- Bump in adjacent machines' coin-in.

**Operator answer:** See [bill-validator-troubleshooting.md]. The
hold gap is a symptom of the fault, not a configuration issue.

## 4. Meter reconciliation gap

**Setup:** Event-derived `coin_in_cents` for a machine does not match
the next meter poll delta. This should look like a data-quality or
monitoring issue, not a game fairness issue.

**Signal:**
- Mismatch between summed event `coin_in_delta_cents` and `METER_POLL`
  `coin_in_cents` for the same machine over the same window.
- No corresponding `JACKPOT_HANDPAY` or `CONFIG_CHANGE` event.

**Operator answer:** "Open an investigation against the OSMS feed.
This is a feed-integrity issue, not a fairness issue. The
`verify-run` script flags this same condition for synthetic runs."

## 5. Configuration baseline shift

**Setup:** A paytable changes during the day, moving theoretical hold
from 7.5% to 8.2%. If analytics compare post-change performance to
the old baseline, it looks like hold drift.

**Signal:**
- `CONFIG_CHANGE` event for the machine.
- New `paytable_id`.
- New `theoretical_hold_pct`.
- Apparent anomaly disappears when segmented by config window.

**Operator answer:** "Segment by `paytable_id` and compare post-change
performance only to the new baseline. The drift is by design — an
approved math change."

## 6. Occupancy mix shift

**Setup:** The bar becomes attractive during a simulated event.
Nearby banks get more casual, lower-denomination play, while a
high-limit/high-volatility bank has fewer but larger sessions.

**Signal:**
- Spike in `BAR_VISIT` events.
- Bank-level traffic mix shift (denomination mix changes).
- Different volatility mix among active sessions.
- Floor-level `actual_hold_pct` changes without per-machine issues.

**Operator answer:** "Don't tune machines for the floor-level hold
movement. The cause is bank-level mix shift driven by bar traffic;
expected behavior."
