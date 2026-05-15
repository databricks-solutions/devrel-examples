# Progressive jackpot rules

The casino floor has one progressive jackpot pool. Eligible wagers
contribute a small percentage of each bet to a shared meter; when a
jackpot hits, the meter resets to its seed value and the hand-paid
award is recorded.

## Eligibility

- **Eligible machines:** Any slot marked `progressive_eligible: true`
  in its PAR sheet. In the demo this currently means every machine.
- **Eligible wagers:** All `BET_SETTLED` events emit a
  `progressive_contribution_delta_cents` value derived from the bet
  amount. For the demo, contribution = `max(1, round(bet * 0.0125))`
  cents — i.e. about 1.25% of each wager.

## Meter math

- `current_meter_cents = seed_meter_cents + sum(progressive_contribution_delta_cents)`
  across the period since the last reset, regardless of which eligible
  machine generated the contribution.
- The meter is **shared** across the pool. A hand-pay on slot-014
  resets the meter for the whole bank, not just for slot-014.

## Hit mechanics

- A jackpot hits stochastically based on the machine's volatility
  class. Higher volatility machines have a higher per-spin chance to
  trigger.
- When a jackpot hits, the simulator emits a `JACKPOT_HANDPAY` event
  with the full hand-pay amount in `jackpot_handpay_delta_cents`. The
  meter resets to seed.

## Operator implications

- A jackpot hit will visibly distort actual hold for the affected
  bank — by design. In silver/gold analytics, look at
  `jackpot_adjusted_hold_pct = (coin_in - coin_out - jackpot_handpay) / coin_in`
  to see the ex-jackpot picture.
- Don't pull a high-volatility machine for "poor hold" if its
  coin-in is low and a recent hand-pay explains the gap. Wait for the
  bank to accumulate ~$10k of eligible coin-in post-reset before
  drawing conclusions.

## Educational disclaimer

Real progressive systems are governed by jurisdiction-specific rules
(GLI-12, UKGC RTS 9). The demo uses simplified math suitable for an
educational simulation.
