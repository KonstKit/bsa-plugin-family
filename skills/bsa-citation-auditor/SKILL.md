---
name: bsa-citation-auditor
description: Audit Stage 7-8 and discovery D5 candidate outputs for citation completeness and overclaim risk using canonical claim-layer controls A58/A59/A60.
---

# BSA Citation Auditor

Run this skill before readiness promotion.

## Scope
- Verify that critical statements map to canonical claim-layer evidence.
- Detect unsupported or weakly supported claims.
- Classify critical unsupported claims for `KPI-003`.
- Reuse the same citation and overclaim logic for D5 discovery synthesis outputs when discovery is enabled.

## Invocation Modes
- Main cycle:
  - Read from `analysis/proposals/stage7_8/stage7/` plus canonical `A58/A59/A60`.
  - Write `citation_audit_report.md|json` into `analysis/proposals/stage7_8/stage7/`.
  - Supports optional marker `stage7.citation_audit.pass.json` when enabled by run profile.
- Discovery (D5):
  - Read from `analysis/discovery/proposals/d5/` plus discovery claim-layer controls.
  - Write `discovery_citation_audit_report.md` into `analysis/discovery/proposals/d5/`.
  - Supports marker `discovery.d5.citation_audit.pass.json`.
- Mode is routed by orchestrator; do not self-select mode from chat text.

## Inputs
- Canonical/discovery `A58/A59/A60` according to active mode.
- Candidate synthesis package in active mode proposal path.

## Outputs
- `analysis/proposals/stage7_8/stage7/citation_audit_report.md`
- `analysis/proposals/stage7_8/stage7/citation_audit_report.json`
- `analysis/discovery/proposals/d5/discovery_citation_audit_report.md`

## Workflow
1. Read canonical `A58/A59/A60` and Stage 7/8 proposal outputs.
2. Build citation coverage table (`statement -> ClaimID/A51Ref`).
3. Flag unsupported critical claims.
4. Emit `citation_audit_report.md` and `citation_audit_report.json` in `analysis/proposals/stage7_8/stage7/`.
5. For discovery reuse, emit `discovery_citation_audit_report.md` in `analysis/discovery/proposals/d5/`.

## Invariant
- Readiness cannot pass when critical unsupported claims > 0.

## On Audit Failure
1. Emit failing report with statement-level findings.
2. Do not emit pass marker.
3. Route unresolved evidence gaps to shared `A51`.
4. Request producer rework in the same mode path and re-audit.

## Reference
- [references/citation-and-overclaim.md](references/citation-and-overclaim.md)
