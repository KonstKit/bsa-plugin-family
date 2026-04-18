---
name: bsa-handoff-packager
description: Assemble consumer-specific H1-H4 handoff proposals from validated canonical outputs with quote-fidelity and no-new-claims enforcement (legacy report naming may still use no-new-facts).
---

# BSA Handoff Packager

Use this skill after Stage 8 no-new-claims pass.

## Scope
- Build `H1-H4` package proposals from validated canonical artifacts only.
- Enforce quote-fidelity to canonical claim-layer (`A58/A59`).
- Prevent new-claim leakage in package outputs (`KPI-005`).
- Keep discovery `Discovery Report/Brief` as non-canonical wording aids only; they can seed wording but cannot add facts beyond canonical claim-layer.

## Inputs
- `analysis/canonical/stage8/readiness_assessment.md`
- `analysis/canonical/stage8/readiness_profile_scorecard.md`
- `analysis/canonical/stage7/validation_report.md`
- `analysis/canonical/core_controls/A58_evidence_excerpts.csv`
- `analysis/canonical/core_controls/A59_claim_register.csv`
- `analysis/canonical/core_controls/A51_issue_route_register.csv`

## Outputs
- `analysis/proposals/stage7_8/handoff/H1_exec_brief.md`
- `analysis/proposals/stage7_8/handoff/H2_delivery_packet.md`
- `analysis/proposals/stage7_8/handoff/H3_validation_packet.md`
- `analysis/proposals/stage7_8/handoff/H4_open_items_packet.md`
- `analysis/proposals/stage7_8/handoff/handoff_manifest.json`
- `analysis/proposals/stage7_8/handoff/handoff_evidence_binding_map.csv`

## Workflow
1. Read canonical Stage 8 outputs, canonical artifact map, and canonical control surfaces.
2. Build H1-H4 packages by consumer profile.
3. Attach claim references or `A51Ref` to every high-impact statement.
4. Emit package outputs under `analysis/proposals/stage7_8/handoff/`.
5. Submit outputs to `bsa-no-new-facts-auditor` before promotion.

## Invariant
- Once a canonical equivalent exists, raw proposal folders are not valid fact sources for package generation.

## On Audit Failure
1. Read handoff no-new-facts findings.
2. Revise proposal-layer H1-H4 and manifest only.
3. Route unresolved wording disputes via `A51Ref`.
4. Re-submit handoff package for no-new-facts verification.

## Validation Binding
- `SCN-STAGE78-001-E`: H1-H4 generated without new-claim leakage.

## Reference
- [references/handoff-contract.md](references/handoff-contract.md)
