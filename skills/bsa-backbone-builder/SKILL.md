---
name: bsa-backbone-builder
description: Select active analytical path and build Stage 5 backbone proposals plus anchor provenance candidates for downstream A61 promotion.
---

# BSA Backbone Builder

Run this skill for Stage 5 path-sensitive backbone construction.

## Scope
- Select active path (`process` or `structural`).
- Build Stage 5 backbone for active path.
- Produce Stage 5 anchor provenance candidates consumed by `bsa-anchor-auditor` and later by `A61`.

## Mandatory Reference Load
- Read [references/path-selection.md](references/path-selection.md) before authoring outputs.

## Inputs
- `analysis/canonical/stage4/` promoted Stage 4 catalogs and glossary.
- `analysis/canonical/core_controls/A59_claim_register.csv` for claim lineage.
- `analysis/canonical/core_controls/A51_issue_route_register.csv` for unresolved route constraints.
- Optional Stage 2 context surfaces (`analysis/canonical/stage2/*`) when path choice depends on context framing.

## Outputs
- `analysis/proposals/stage5/path_decision_note.md`
- `analysis/proposals/stage5/process_backbone.md` or `analysis/proposals/stage5/decision_data_state_backbone.md`
- `analysis/proposals/stage5/stage5_anchor_candidates.csv`
- `analysis/proposals/stage5/stage5_anchor_provenance.csv`
- `analysis/proposals/stage5/backbone_trace_report.md`

## Invariants
- Path choice must be justified from promoted Stage 4 evidence and open `A51` routes.
- Backbone proposals cannot introduce unbound steps, decisions, or boundaries.
- This worker emits candidates only; Stage 5 anchor audit is owned by `bsa-anchor-auditor`.

## On Audit Failure
1. Read Stage 5 anchor audit findings.
2. Fix only Stage 5 proposal artifacts owned by this skill.
3. Re-emit updated proposal artifacts and trace report.
4. Request re-audit; do not write canonical Stage 5 or `A61`.

## Validation Binding
- `SCN-STAGE46-001-B`: explicit path choice.
- `SCN-STAGE46-001-C`: backbone aligned to path.
- `SCN-STAGE46-001-E`: anchor-ready provenance for critical Stage 5 elements.

## Reference
- [references/path-selection.md](references/path-selection.md)
