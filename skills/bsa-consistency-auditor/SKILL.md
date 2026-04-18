---
name: bsa-consistency-auditor
description: Run cross-artifact consistency checks across canonical outputs, sidecar views, and anchor manifests, then emit Stage 7 and discovery D5 audit findings.
---

# BSA Consistency Auditor

Use this skill before readiness promotion.

## Scope
- Check canonical term/boundary consistency.
- Check BPMN/C4 anchor manifests against canonical `A61` with typed `AnchorClass` compatibility (`actor|system|process|contract|boundary`).
- Detect derived-view drift and traceability breaks.
- Reuse consistency checks for D5 discovery synthesis outputs as pre-handoff controls.
- Treat class mismatch, semantic mismatch, missing mapping, unknown anchor, and broken claim-binding as blocking findings.

## Invocation Modes
- Main cycle:
  - Read Stage 7 proposal package and canonical anchors.
  - Write consistency reports to `analysis/proposals/stage7_8/stage7/`.
  - Supports marker `stage7.consistency_audit.pass.json` in doc-level governance.
- Discovery (D5):
  - Read D5 synthesis package and discovery-side anchor references.
  - Write report to `analysis/discovery/proposals/d5/`.
  - Discovery findings remain non-canonical.
- Mode is selected by orchestrator routing, not by self-detection.

## Inputs
- Candidate artifacts from the active mode proposal directory.
- Canonical `A61`/anchor manifests and claim-layer controls.

## Output
- `analysis/proposals/stage7_8/stage7/consistency_audit_report.md`
- `analysis/proposals/stage7_8/stage7/consistency_audit_report.json`
- `analysis/discovery/proposals/d5/discovery_consistency_audit_report.md`

## Invariant
- Auditor findings are proposal-layer findings only; pass markers are orchestrator-owned after report validation.

## On Audit Failure
1. Emit full mismatch taxonomy with blocker/non-blocker split.
2. Do not request canonical promotion.
3. Route unresolved anchor conflicts to `A51`.
4. Re-audit only after producer-side proposal rework.

## Reference
- [references/consistency-contract.md](references/consistency-contract.md)
