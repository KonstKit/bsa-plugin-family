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
- No claim in `A59` without `SourceID` and `ExcerptID`.
- No excerpt in `A58` is valid without a reproducible locator.
- Inference claims must expose their basis; they cannot masquerade as direct quotes.
- Positive factual claims are never authored from `A51` alone.
- Claim-layer remains proposal-only until orchestrator promotion.

## On Audit Failure
1. Read claim-layer findings and missing-column/binding diagnostics.
2. Correct only Stage 1 proposal artifacts.
3. Route unresolved ambiguity to `A51Ref` instead of fabricating fact rows.
4. Re-submit for Stage 1 merge validation.

## Validation Binding
- `SCN-STAGE13-001-C`: build `A58` and `A59` before semantic merge.
- `SCN-STAGE13-001-B`: produce `A60` from contradiction and missing-source findings.

## Reference
- [references/claim-layer.md](references/claim-layer.md)
