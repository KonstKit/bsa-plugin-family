# Handoff Contract

## Required Outputs
- `H1_exec_brief.md`
- `H2_delivery_packet.md`
- `H3_validation_packet.md`
- `H4_open_items_packet.md`
- `handoff_manifest.json`

## Rules
- Every decision-bearing or high-impact statement must carry `ClaimID` or `A51Ref`.
- `H4` is the only valid sink for unresolved items; unresolved items must not be silently blended into `H1-H3`.
- Wording may compress canonical content, but cannot introduce new claims, actors, constraints, or commitments.
