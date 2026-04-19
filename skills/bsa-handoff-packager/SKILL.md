---
name: bsa-handoff-packager
description: Assemble consumer-specific H1-H4 handoff proposals from validated canonical outputs with quote-fidelity and no-new-claims enforcement (INV-03). ClaimType=analyst_judgment rows in H1/H4 are allowed when JustificationRationale references upstream ClaimIDs (INV-07).
---

# BSA Handoff Packager

Use this skill after Stage 8 no-new-claims pass.

## Scope
- Build `H1-H4` package proposals from validated canonical artifacts only.
- Enforce quote-fidelity to canonical claim-layer (`A58/A59`).
- Prevent new-claim leakage in package outputs (`KPI-005`).
- Keep discovery `Discovery Report/Brief` as non-canonical wording aids only; they can seed wording but cannot add claims beyond canonical claim-layer.

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
5. Submit outputs to `bsa-no-new-claims-auditor` before promotion.

## Invariant
- Once a canonical equivalent exists, raw proposal folders are not valid claim sources for package generation.

## On Audit Failure
1. Read handoff no-new-claims findings.
2. Revise proposal-layer H1-H4 and manifest only.
3. Route unresolved wording disputes via `A51Ref`.
4. Re-submit handoff package for no-new-claims verification.

## Validation Binding
- `SCN-STAGE78-001-E`: H1-H4 generated without new-claim leakage (aggregate).
- `SCN-STAGE78-001-E-H1` / `-E-H2` / `-E-H3` / `-E-H4`: per-pack shape and citation closure.

## References
- [references/handoff-contract.md](references/handoff-contract.md) — cross-pack rules + manifest pointer.
- [references/h1_spec.md](references/h1_spec.md) — H1 executive brief content contract.
- [references/h2_spec.md](references/h2_spec.md) — H2 delivery packet content contract.
- [references/h3_spec.md](references/h3_spec.md) — H3 validation packet content contract.
- [references/h4_spec.md](references/h4_spec.md) — H4 open items packet content contract.
- [references/handoff_manifest.schema.json](references/handoff_manifest.schema.json) — JSON schema for `handoff_manifest.json`.
