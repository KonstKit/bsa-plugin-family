# Handoff Contract

Cross-pack rules for the H1-H4 handoff bundle produced by `bsa-handoff-packager`. Per-pack content contracts live in the peer spec files; this document defines what applies across all four packs plus the manifest.

## Required Outputs
- `H1_exec_brief.md` — see [h1_spec.md](h1_spec.md) for content contract.
- `H2_delivery_packet.md` — see [h2_spec.md](h2_spec.md).
- `H3_validation_packet.md` — see [h3_spec.md](h3_spec.md).
- `H4_open_items_packet.md` — see [h4_spec.md](h4_spec.md).
- `handoff_manifest.json` — conforms to [handoff_manifest.schema.json](handoff_manifest.schema.json).
- `handoff_evidence_binding_map.csv` — cross-reference of every `[C-xxx]` / `[AJ:C-xxx]` / `[A51-xxx]` citation used across H1-H4 back to its canonical origin (A59 / A51). One row per citation occurrence.

## Output Locations (v1.3.7+)

The six required outputs live at TWO paths during a single `/bsa-handoff` invocation:

1. **Worker (proposal) location** — `analysis/proposals/stage7_8/handoff/` — gated by the F5 dispatcher + the no-new-claims auditor before the route step fires. Worker writes happen here exclusively.

2. **Terminal (operator-facing) location** — `analysis/handoff/` — after the no-new-claims auditor passes, the orchestrator copies each file byte-for-byte to this path. The terminal copies are what every downstream consumer reads (`/bsa-dev-handoff`, dashboard, backlog-bridge). Pre-v1.3.7 the routing step was implicit; consumers found nothing at the terminal path because the SKILL.md only documented the proposal location and there was no explicit step to move/copy.

The route is a copy, not a regenerate — the manifest's checksum (computed at the proposal location over the byte-identical files) remains valid at the terminal location.

## Rules
- Every decision-bearing or high-impact statement must carry `ClaimID` or `A51Ref`.
- `H4` is the only valid sink for unresolved items; unresolved items must not be silently blended into `H1-H3`.
- Wording may compress canonical content, but cannot introduce new claims, actors, constraints, or commitments (INV-03).
- `ClaimType=analyst_judgment` rows are permitted in H1 `## Recommended Next Steps` and H4 `## Decisions Required` when tagged `[AJ:C-xxx]` and the referenced A59 row's `JustificationRationale` references ≥ 1 upstream `ClaimID` different from its own (INV-07).
- The manifest checksum covers H1 + H2 + H3 + H4 + `handoff_evidence_binding_map.csv` in that exact order; any out-of-order emission is a shape violation.

## Cross-References
- Content specs: `h1_spec.md`, `h2_spec.md`, `h3_spec.md`, `h4_spec.md`.
- Manifest schema: `handoff_manifest.schema.json`.
- Audit binding: `skills/bsa-no-new-claims-auditor/references/no-new-claims-contract.md` (H-pack gate).
- Terminology: `docs/sem_audit_rename.md`.
- Invariants: `governance/immutable_invariants.md` INV-01 / INV-03 / INV-07.
