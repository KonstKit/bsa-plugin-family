# Traceability Contract

Use this file when the BPMN must be auditable against documents, transcripts, or workshop notes.

## Minimum Traceability Payload

For every material task, gateway, exception branch, and end state, keep:

- `element_id`
- `element_type`
- `source_reference`
  - document name, transcript section, page, timestamp, or note identifier
- `evidence_type`
  - `explicit`, `inferred`, or `assumed`
- `confidence`
  - `high`, `medium`, or `low`
- `rationale`
  - one short sentence
- `open_question`
  - blank if none

## Delivery Rule

When the source is multi-document, ambiguous, or analyst-facing:

- include a compact traceability table in the final response, or
- write a sidecar markdown file next to the `.bpmn`

## Hard Rule

If a branch, timer, escalation, or runtime-specific task type is not directly evidenced:

- mark it as `inferred` or `assumed`
- never present it as fully explicit process truth
