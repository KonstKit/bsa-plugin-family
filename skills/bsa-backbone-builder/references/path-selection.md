# Path Selection Contract

## Required Outputs
- `path_decision_note.md`
- `process_backbone.md` or `decision_data_state_backbone.md`
- `stage5_anchor_candidates.csv`
- `backbone_trace_report.md`

## Path Choice Rules
- Choose `process` when dominant evidence is about actors, sequence, handoffs, triggers, approvals, or operational flow.
- Choose `structural` when dominant evidence is about decision logic, data state, invariants, calculations, or boundary conditions.
- If signals are mixed, document tie-break logic and unresolved alternatives in `A51`.

## Anchor Candidate Columns
- `AnchorID`
- `ElementID`
- `ElementType`
- `AnchorClass` (`actor|system|process|contract|boundary`)
- `ClaimID` or `A51Ref`
