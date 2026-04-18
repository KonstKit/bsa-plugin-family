# Review Mode

Use this file when the user supplies an existing `.bpmn` and asks for review, repair, or refinement.

## Workflow

1. Load the current BPMN graph and BPMNDI.
2. Extract the source-context process map from the supplied documents.
3. Match source-context steps to BPMN elements.
4. Build a gap list with one line per issue:
   - missing branch
   - wrong task or event type
   - ambiguous gateway meaning
   - missing end outcome
   - invalid or unreadable layout
5. Distinguish:
   - graph defects
   - layout defects
   - source ambiguity
6. Apply the smallest safe fix.
7. Preserve readable geometry unless a local repair cannot work.
8. Re-run semantic validation and layout validation.

## Decision Rules

- If the graph is structurally wrong, fix the graph first and layout second.
- If the graph is correct and only BPMNDI is poor, keep BPMN logic unchanged.
- If the source is ambiguous, ask instead of inventing undocumented branches.

## Output

Report:

- what changed
- what remained unchanged
- which assumptions were introduced
- whether geometry was preserved locally or re-laid out
