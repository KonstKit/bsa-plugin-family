# Claim Layer Contract

## Output Files
Write under `analysis/proposals/stage1/`:
- `A58_evidence_excerpts.csv`
- `A59_claim_register.csv`
- `A60_negative_evidence_register.csv`
- `stage1_claim_binding_report.md`

## Required Columns

### A58
- `ExcerptID`
- `SourceID`
- `FragmentID`
- `LocatorType`
- `LocatorValue`
- `SpeakerOrSection` (optional)
- `ExcerptText`
- `QuoteHash`
- `ExtractionMethod`
- `InterpretationNote`

### A59
- `ClaimID`
- `SourceID`
- `ExcerptID`
- `ClaimText`
- `ClaimType` (`direct`, `inference`)
- `BasisClaimIDs` (required when `ClaimType = inference`)
- `Confidence`
- `A51Ref` (optional)

### A60
- `NegativeEvidenceID`
- `SourceID`
- `ExcerptID` (optional)
- `GapOrContradiction`
- `A51Ref`
- `BlockingStatus`

## Quality Rules
- `A59` direct-claim coverage must be measurable for `KPI-001`.
- Inference claims must cite the basis claim(s); otherwise they are invalid.
- Contradictions and missing proof must be represented in `A60`, not hidden in prose.
- If a proposed claim introduces an entity, event, or boundary not present in the bound excerpt set, route it to `A51` and do not promote it without evidence-binding.
