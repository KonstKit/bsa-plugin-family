# KPI Definitions

## KPI-001: Direct Claim Coverage Ratio
- Definition: ratio of direct claims with bound `SourceID+ExcerptID` to total direct claims in `A59`.
- Formula: `covered_direct_claims / total_direct_claims`.
- Default target: `>= 0.90`.

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
