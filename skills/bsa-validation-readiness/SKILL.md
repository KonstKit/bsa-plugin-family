---
name: bsa-validation-readiness
description: Execute Stage 7 and Stage 8 validation/readiness workflow after mandatory citation, consistency, skeptical, and no-new-claims audits (INV-03 leakage gate; analyst_judgment rows treated per INV-07).
---

# BSA Validation Readiness

Run this skill for Stage 7/8 control flow.

## Scope
- Assemble Stage 7 review pack.
- Integrate citation + consistency + skeptical + no-new-claims audits.
- Produce validation outcome independent from readiness label/profile.
- Enforce `KPI-003`, `KPI-004`, and `KPI-005` readiness gates.
- When discovery branch is enabled, allow D5 outputs (`Discovery Report`, `Discovery Brief`) to reuse the same audit logic as non-canonical pre-entry checks.

## Inputs
- `analysis/proposals/stage7_8/stage7/` audit reports and review artifacts.
- `analysis/proposals/stage7_8/stage8/` readiness and no-new-claims artifacts.
- Shared controls `analysis/canonical/core_controls/A51_issue_route_register.csv` and claim-layer controls.

## Outputs
- Stage 7 readiness package updates in `analysis/proposals/stage7_8/stage7/`.
- Stage 8 readiness package updates in `analysis/proposals/stage7_8/stage8/`.
- Discovery reuse findings in `analysis/discovery/proposals/d5/` when branch is enabled.

## Gate Rules
- `KPI-003`: critical unsupported claims must equal `0`.
- `KPI-004`: consistency verdict must be `PASS` and unanchored derived-view elements must equal `0`.
- `KPI-005`: Stage 8 and handoff no-new-claim leakage must equal `0`.
- Readiness decision requires the active run profile marker set, including `stage7.skeptical_review.pass` and `stage8.no_new_claims.pass` in runtime contract.
- Run-profile gate sets are defined by orchestrator reference `bsa-orchestrator/references/run-profile-gates.md`.

## On Audit Failure
1. Mark readiness as failed and keep outputs proposal-layer.
2. Emit explicit blocker list mapped to upstream artifacts.
3. Route unresolved blockers to `A51Ref`.
4. Request targeted rework for failing stage and re-run gates.

## Validation Binding
- `SCN-STAGE78-001-A`: review pack assembly.
- `SCN-STAGE78-001-B`: mandatory audits before readiness.
- `SCN-STAGE78-001-C`: validation outcome separated from readiness.
- `SCN-STAGE78-001-D`: readiness label + profile.
- `SCN-DISC-001`: discovery synthesis audit reuse stays subordinate to discovery governance.

## Reference
- [references/review-and-readiness.md](references/review-and-readiness.md)
