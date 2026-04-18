---
name: bsa-contract-builder
description: Build Stage 6 contract-layer proposals aligned to the selected path and produce an auditable A61 candidate map for orchestrator promotion.
---

# BSA Contract Builder

Run this skill for Stage 6 contract-layer construction.

## Scope
- Build active contract family.
- Build boundary and fallback semantics.
- Consolidate Stage 4-6 anchor provenance into an `A61` candidate map.

## Mandatory Reference Load
- Read [references/contract-layer-selection.md](references/contract-layer-selection.md) before producing Stage 6 artifacts.

## Inputs
- `analysis/canonical/stage5/path_decision_note.md`
- `analysis/canonical/stage5/process_backbone.md` or `analysis/canonical/stage5/decision_data_state_backbone.md`
- `analysis/canonical/stage5/stage5_anchor_provenance.csv`
- `analysis/canonical/core_controls/A59_claim_register.csv`
- `analysis/canonical/core_controls/A51_issue_route_register.csv`

## Outputs
- `analysis/proposals/stage6/contract_layer_decision.md`
- `analysis/proposals/stage6/interface_contract_model.md` or `analysis/proposals/stage6/data_rule_state_contract_pack.md`
- `analysis/proposals/stage6/boundary_input_output_map.md`
- `analysis/proposals/stage6/error_fallback_notes.md`
- `analysis/proposals/stage6/A61_anchor_map_candidate.csv`

## Invariants
- No interface, state, or boundary may be introduced without upstream `ClaimID` or explicit `A51Ref`.
- This worker emits `A61` candidates only; canonical `A61` is orchestrator-owned after anchor audit pass.

## On Audit Failure
1. Read Stage 6 anchor audit findings.
2. Revise Stage 6 proposal artifacts and `A61` candidate map.
3. Ensure every changed row stays evidence-bound (`ClaimID` or `A51Ref`).
4. Re-submit for anchor audit; never write canonical `A61` directly.

## Validation Binding
- `SCN-STAGE46-001-D`: contract layer aligned to path.
- `SCN-STAGE46-001-E`: `A61` anchor map prepared and auditable.

## Reference
- [references/contract-layer-selection.md](references/contract-layer-selection.md)
