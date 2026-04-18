---
name: bsa-anchor-auditor
description: Audit Stage 5 and Stage 6 anchor candidates for evidence binding, class compatibility, and orphan elements before orchestrator promotion.
---

# BSA Anchor Auditor

Use this skill after Stage 5 and Stage 6 builders produce anchor candidates.

## Scope
- Audit `stage5_anchor_candidates.csv`.
- Audit `A61_anchor_map_candidate.csv`.
- Verify every anchor has `ClaimID` or explicit `A51Ref`.
- Verify `AnchorClass` compatibility for downstream BPMN/C4 manifests.
- Detect orphan, duplicated, or semantically drifting anchors.

## Inputs
- `analysis/proposals/stage5/stage5_anchor_candidates.csv`
- `analysis/proposals/stage5/stage5_anchor_provenance.csv`
- `analysis/proposals/stage6/A61_anchor_map_candidate.csv`
- `analysis/canonical/core_controls/A59_claim_register.csv`
- `analysis/canonical/core_controls/A51_issue_route_register.csv`

## Outputs
- `analysis/proposals/stage5/anchor_audit_report.md`
- `analysis/proposals/stage5/anchor_audit_report.json`
- `analysis/proposals/stage6/anchor_audit_report.md`
- `analysis/proposals/stage6/anchor_audit_report.json`

## Gate Rule
- `stage5.anchor_audit.pass.json` requires verdict `PASS`.
- `stage6.anchor_audit.pass.json` requires verdict `PASS`.

## On Audit Failure
1. Emit stage-specific failing report with mismatch taxonomy.
2. Do not emit pass marker.
3. Route unresolved class/binding conflicts to `A51`.
4. Request rework from Stage 5/6 producer and re-audit.

## Reference
- [references/anchor-audit-contract.md](references/anchor-audit-contract.md)
