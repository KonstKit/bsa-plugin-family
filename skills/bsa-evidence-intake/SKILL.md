---
name: bsa-evidence-intake
description: Intake heterogeneous project sources, produce machine-readable source inventory and coverage notes, run contradiction and missing-source scan, and prepare Stage 1 proposal artifacts for claim-layer binding and orchestrator merge.
---

# BSA Evidence Intake

Run this skill for Stage 1 intake.

## Scope
- Inventory project sources and metadata.
- Build machine-readable `source_manifest.csv` plus narrative source coverage notes.
- Run cross-source contradiction scan.
- Capture missing sources and access gaps.
- Seed `A50/A51` and provide upstream material for `A58/A60`.

## Inputs
- User-provided project materials (docs, sheets, transcripts, tickets, repos, notes).
- Existing shared controls `analysis/canonical/core_controls/A50_source_register.csv` and `A51_issue_route_register.csv` when present.

## Outputs
- `analysis/proposals/stage1/source_inventory.md`
- `analysis/proposals/stage1/source_manifest.csv`
- `analysis/proposals/stage1/source_coverage.md`
- `analysis/proposals/stage1/contradiction_scan.md`
- `analysis/proposals/stage1/missing_sources.md`
- `analysis/proposals/stage1/A50_source_register.csv` (proposal-layer seed/update)
- `analysis/proposals/stage1/A51_issue_route_register.csv` (proposal-layer seed/update)

## Workflow
1. Inventory explicit and implicit sources.
2. Record source strength, access status, and priority notes.
3. Run contradiction scan across top-priority readable sources.
4. Record missing-source entries and blocking status.
5. Write proposals under `analysis/proposals/stage1/`.

## Invariants
- Conflicts are never collapsed into assumptions.
- Missing or unreadable evidence must stay explicit.
- Unavailable source contents must never be inferred from surrounding chat.
- This worker inventories and routes evidence; it does not author domain claims.
- Canonical writes are forbidden for this worker.

## On Audit Failure
1. Keep failed outputs in proposal layer.
2. Add missing-source or contradiction routes to `A51Ref`.
3. Regenerate Stage 1 intake artifacts with explicit evidence provenance.
4. Re-run Stage 1 intake checks before claim binding.

## Validation Binding
- `SCN-STAGE13-001-A`: inventory + coverage + missing-source outputs.
- `SCN-STAGE13-001-B`: contradiction scan + `A50/A51` seed + `A60` candidates.

## Reference
- [references/source-intake.md](references/source-intake.md)
