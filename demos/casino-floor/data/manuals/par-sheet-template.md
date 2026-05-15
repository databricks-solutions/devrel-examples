# PAR sheet — slot machine summary

A PAR (Probability & Accounting Report) sheet documents the approved
math configuration of a slot machine. Every machine on the floor has
exactly one active PAR sheet at any time. When the paytable is changed,
a new PAR sheet is approved and the old one is archived.

This document is the **template**; per-machine sheets follow this
structure with values filled in.

## Identification

| Field | Description |
| --- | --- |
| `machine_id` | Internal slot id, e.g. `slot-014`. |
| `bank_id` | Logical bank the machine sits in (A, B, C, D in the demo). |
| `theme` | Game theme as marketed: Neon Buffalo, Lucky Lanterns, Moonlight 7s. |
| `paytable_id` | Versioned paytable identifier, e.g. `PAR-SLOT-014-925`. |
| `denomination_cents` | Credit value in cents. |
| `volatility_class` | LOW / MEDIUM / HIGH. Controls hit frequency vs payout size. |
| `progressive_eligible` | Whether eligible wagers contribute to a progressive jackpot pool. |

## Theoretical math

| Field | Description |
| --- | --- |
| `theoretical_rtp_pct` | Long-run return to player as a percentage. 92.5% is typical for our medium-vol mix. |
| `theoretical_hold_pct` | `100 - theoretical_rtp_pct`. Operator-facing inverse framing. |
| `max_bet_credits` | Maximum credits permitted per spin. |
| `min_bet_credits` | Minimum credits permitted per spin. |
| `hit_frequency_pct` | Approximate proportion of spins that return a non-zero payout. |
| `top_award_credits` | Largest possible single-spin award (excluding progressive). |

## Volatility expectations (operator guidance)

- **LOW** — frequent small wins, tight short-term hold around theoretical.
  False-positive risk on hold is low even at modest coin-in.
- **MEDIUM** — occasional medium wins, visible short-term variance. Hold
  needs ~$2,000–$5,000 of coin-in before being meaningful.
- **HIGH** — rare large payouts. Hold is meaningless under ~$10k coin-in
  and any single jackpot can shift hold by tens of percentage points.

## Where this sheet is referenced

- The **Machine inspector** in the app shows the live values for the
  selected slot's active PAR sheet.
- Genie joins `silver_slot_spins.paytable_id` back to the PAR sheet so
  hold gaps can be segmented by paytable version.
- A `CONFIG_CHANGE` event signals that a new PAR sheet is now active.

## Educational disclaimer

These fields are derived from public-domain regulator descriptions
(Nevada Reg 14 Technical Standard 3, UKGC RTS 7) — no PAR sheet in this
repository represents an approved real-world configuration.
