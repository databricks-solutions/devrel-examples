# Casino floor operations corpus

A small synthetic corpus of operations manuals, regulatory notes, and
maintenance procedures used by a slot floor team. This is **educational
content** — it borrows language and structure from real gaming standards
(GLI / Nevada Reg 14 / UKGC RTS) but no document here represents an
approved policy or certified rule.

Eventually this corpus is intended to be indexed by a Knowledge Assistant
in the Databricks app so policy/explanation questions ("why might hold
drift mid-shift?", "what's the TTR target for a bill validator soft
fault?") can be answered by retrieval rather than by Genie's SQL path.

## Files

- `par-sheet-template.md` — generic PAR (theoretical hold) sheet shape
  with field definitions, used as the per-machine summary template.
- `bill-validator-troubleshooting.md` — diagnostic flowchart for the
  most common cabinet-side fault we model in the demo.
- `progressive-rules.md` — contribution percentages, seeding, eligible
  wagers, and reset behavior for the floor's progressive bank.
- `maintenance-log-template.md` — fields and severity classification for
  a maintenance ticket; what an attendant fills out when a slot faults.
- `floor-narratives.md` — the six anomaly narratives the demo seeds and
  the operator-level explanation for each.

## License & provenance

All content here is original, written for this demo. Footnotes reference
public-domain regulator/standard URLs for orientation, not for
verbatim quoting.
