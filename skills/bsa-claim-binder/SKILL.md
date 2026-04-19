---
name: bsa-claim-binder
description: Build Stage 1 claim-layer proposal surfaces A58/A59/A60 by extracting evidence excerpts with locators, binding claims to excerpts, and capturing negative evidence linked to A51.
---

# BSA Claim Binder

Run this skill inside composite Stage 1, after intake and before semantic extraction.

## Scope
- Build `A58` evidence excerpt register with reusable source locators.
- Build `A59` claim register with explicit excerpt linkage.
- Build `A60` negative-evidence register for contradictory or missing proof.

## Inputs
- `analysis/proposals/stage1/source_manifest.csv`
- `analysis/proposals/stage1/source_inventory.md`
- `analysis/proposals/stage1/source_coverage.md`
- `analysis/proposals/stage1/contradiction_scan.md`
- `analysis/proposals/stage1/missing_sources.md`
- Shared controls `analysis/canonical/core_controls/A50_source_register.csv` and `A51_issue_route_register.csv` when available

## Outputs
- `analysis/proposals/stage1/A58_evidence_excerpts.csv`
- `analysis/proposals/stage1/A59_claim_register.csv`
- `analysis/proposals/stage1/A60_negative_evidence_register.csv`
- `analysis/proposals/stage1/stage1_claim_binding_report.md`

## Workflow
1. Read Stage 1 intake outputs and `source_manifest.csv`.
2. Extract checkable excerpts into `A58`.
3. Bind explicit claims into `A59` with `SourceID` and `ExcerptID`.
4. Record inference basis when `ClaimType = inference`.
5. Capture negative or missing evidence in `A60`, linked to `A51Ref`.
6. Write all outputs under `analysis/proposals/stage1/`.

## Invariants
- `A59.ClaimType` is closed to exactly `{direct, inference, analyst_judgment}` per `governance/immutable_invariants.md` INV-07.
- `direct` and `inference` rows require `SourceID` and `ExcerptID` (or explicit `A51Ref` when the row guards an unresolved item).
- No excerpt in `A58` is valid without a reproducible locator.
- Inference claims must expose their basis; they cannot masquerade as direct quotes.
- `analyst_judgment` rows are authored ONLY by downstream skills that explicitly own analytical recommendations (e.g. `bsa-context-framer` in Stage 2, `bsa-handoff-packager` in H1/H4). Every such row MUST carry non-empty `JustificationRationale` referencing at least one upstream `ClaimID` different from its own. `bsa-claim-binder` itself does not author `analyst_judgment` rows during Stage 1 intake — its job is the direct/inference claim-layer.
- Positive claims (direct or inference) are never authored from `A51` alone.
- Claim-layer remains proposal-only until orchestrator promotion.

### ClaimStrength propagation (Sprint 3 US-S3-03)
- Every `direct` and `inference` A59 row MUST carry a numeric `ClaimStrength` in `[0.0, 1.0]`.
- `ClaimStrength = max_supporting_tier_weight × (1 - decay_factor)` per `../../bsa-evidence-intake/references/reliability_tier_spec.md`. `max_supporting_tier_weight` is the highest tier weight across all A50 rows whose `SourceID` appears in the ExcerptID's supporting set; decay_factor defaults to 0 in Sprint 3.
- `analyst_judgment` rows leave `ClaimStrength` BLANK — they use JustificationRationale + upstream ClaimID linkage instead of tier weights.
- Tier weights: T1=1.00, T2=0.85, T3=0.65, T4=0.45, T5=0.20. `bsa-claim-binder` never invents tier weights — it reads them from the spec and looks up the source tier from A50. Source rows missing `ReliabilityTier` fail binding with a hard finding.
- For claims with multiple supporting excerpts across sources of different tiers, ClaimStrength takes the MAX of the supporting tier weights (not the mean) — the strongest supporting evidence sets the floor.
- Contested claims (tier-delta ≤ 1 conflict per `reliability_tier_spec.md` §"By tier delta") carry ClaimStrength=0 and a dedicated `ClaimStatus=contested` field on the A59 row until manually resolved; they contribute 0 to KPI-001.
- A claim superseded by a higher-tier contradictory claim carries `SupersededBy=<winning-ClaimID>` in A59 `Notes` and is excluded from KPI-001 numerator.

## On Audit Failure
1. Read claim-layer findings and missing-column/binding diagnostics.
2. Correct only Stage 1 proposal artifacts.
3. Route unresolved ambiguity to `A51Ref` instead of fabricating unsupported claim rows.
4. Re-submit for Stage 1 merge validation.

## Validation Binding
- `SCN-STAGE13-001-C`: build `A58` and `A59` before semantic merge.
- `SCN-STAGE13-001-B`: produce `A60` from contradiction and missing-source findings.

## Reference
- [references/claim-layer.md](references/claim-layer.md)
