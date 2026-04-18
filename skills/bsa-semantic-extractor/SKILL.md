---
name: bsa-semantic-extractor
description: Produce Stage 3 CORE-first semantic rows from canonical claim-layer inputs, apply F/I/A/Q/C decision ladder, and activate Semantic Normalization Pack only by trigger.
---

# BSA Semantic Extractor

Run this skill for Stage 3 semantic extraction.

## Scope
- Build `CORE-first` semantic rows.
- Use one epistemic axis (`F/I/A/Q/C`).
- Preserve traceability to canonical claim-layer controls.
- Activate normalization pack only by trigger.
- Emit a traceability self-check consumed by Stage 3 quality/audit flow before `stage3.citation_audit.pass`.

## Inputs
- `analysis/canonical/core_controls/A59_claim_register.csv`
- `analysis/canonical/core_controls/A58_evidence_excerpts.csv`
- `analysis/canonical/core_controls/A51_issue_route_register.csv`
- Optional normalization trigger configuration.
- Stage 2 artifacts are a runtime gate prerequisite for Stage 3 start, but not a direct semantic row source.

## Outputs
- `analysis/proposals/stage3/semantic_core_rows.md`
- `analysis/proposals/stage3/semantic_traceability_report.md`
- Optional `analysis/proposals/stage3/semantic_normalization_rows.md`

## Workflow
1. Load canonical `A59` claims plus `A51` open-item routes.
2. Split claims into clause-level semantic rows.
3. Assign `F/I/A/Q/C` status.
4. Fill CORE row fields with `ClaimID` or `A51Ref`.
5. If trigger is ON, append normalization rows.
6. Emit `semantic_traceability_report.md`.
7. Write outputs under `analysis/proposals/stage3/`.

## Invariants
- No Stage 3 row is valid without `ClaimID` or explicit `A51Ref`.
- `SourceID` and `ExcerptID` remain mandatory when `ClaimID` is present.
- Stage 3 decomposes upstream claims; it does not create net-new facts, actors, states, or boundaries.
- Normalization pack is non-default.
- Canonical writes are forbidden for this worker.

## On Audit Failure
1. Read Stage 3 audit findings and missing-binding diagnostics.
2. Correct semantic rows and traceability report in proposal layer.
3. Route unresolved decomposition ambiguity to `A51Ref`.
4. Re-run Stage 3 quality flow before promotion.

## Validation Binding
- `SCN-STAGE13-001-D`: CORE rows enforce `ClaimID|A51Ref`.
- `SCN-STAGE13-001-E`: normalization pack is trigger-based only.
- `SCN-STAGE13-001-F`: traceability report is required before Stage 4 promotion.

## References
- [references/core-first-row.md](references/core-first-row.md)
- [references/normalization-pack.md](references/normalization-pack.md)
