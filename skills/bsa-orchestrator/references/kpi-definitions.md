# KPI Definitions

## KPI-001: Weighted Direct-Claim Coverage
- Definition: weighted coverage of direct claims in `A59`, with per-claim contribution derived from the `ReliabilityTier` of its supporting source via the `ClaimStrength` column.
- Formula: `KPI-001 = sum(ClaimStrength for direct claims with bound SourceID+ExcerptID) / count(all direct claims)`.
- `ClaimStrength` is computed per [../../bsa-evidence-intake/references/reliability_tier_spec.md](../../bsa-evidence-intake/references/reliability_tier_spec.md) as `max_supporting_tier_weight × (1 - decay_factor)` (decay_factor defaults to 0 in Sprint 3).
- Contested claims (per the tier-delta ≤ 1 conflict-resolution rule in that spec) contribute 0 to the numerator until manually resolved.
- Default target: `>= 0.75`. This target was re-calibrated when the weighted formula landed in Sprint 3 US-S3-03 (was `>= 0.90` under the unweighted formula because a T5-only fully-covered claim contributes 0.20, not 1.00). Revisit after 3 real projects.
- Reporting: the audit report MUST expose a per-tier breakdown (T1..T5 contribution counts + contributed strength) alongside the aggregate score; see `reliability_tier_spec.md` §"Per-tier breakdown".

## KPI-002: Inference Density Ratio
- Definition: ratio of inference claims to total claims in `A59`.
- Formula: `inference_claims / total_claims`.
- Default target: `<= 0.15`.

## KPI-003: Critical Unsupported Claims
- Definition: count of critical claims without valid `ClaimID` or explicit governed `A51Ref` route.
- Formula: integer count from citation audit outputs.
- Required gate value: `0`.

## KPI-004: Consistency + Anchor Integrity
- Definition: consistency verdict and unanchored derived-view element count.
- Formula:
  - `consistency_verdict` must be `PASS`.
  - `unanchored_derived_elements` must be `0`.
- Required gate value: both conditions true.

## KPI-005: New-Claim Leakage
- Definition: count of net-new claims introduced in Stage 8 or handoff artifacts beyond what is traceable to canonical upstream (INV-03).
- Formula: integer count from `bsa-no-new-claims-auditor` outputs. `ClaimType=analyst_judgment` rows with valid `JustificationRationale` referencing upstream ClaimID are NOT counted as leakage (INV-07); rows with missing or self-only rationale ARE counted.
- Required gate value: `0`.
