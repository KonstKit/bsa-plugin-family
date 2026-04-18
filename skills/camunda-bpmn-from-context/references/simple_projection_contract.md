# Simple Projection / Rehydration Contract

Version: `1.0`

This contract freezes the helper bridge artifact set and the invariant checks required before simple-mode output can be accepted.

## Artifact Set

The bridge always manages these files in the helper work directory:

- `helper_input.bpmn`
- `projection_sidecar.json`
- `helper_output.bpmn`
- `helper_diagnostics.json`

`helper_input.bpmn` is the helper ingress artifact.
`helper_output.bpmn` is the helper egress artifact.
`projection_sidecar.json` records the projection metadata and runtime preservation target.
`helper_diagnostics.json` records helper execution status under the frozen diagnostics schema.

## Projection Sidecar

`projection_sidecar.json` is versioned by `version="1.0"` and contains:

- `source_bpmn`: original source path used for the bridge run
- `projection_mode`: current projection strategy
- `excluded_constructs`: explicit registry of constructs intentionally excluded from the helper payload
- `id_map`: identity/mapping metadata for semantic BPMN IDs
- `runtime_target`: runtime-preservation target, including detected runtime namespaces and preservation requirements

The current passthrough bridge writes an explicit empty `excluded_constructs` list rather than implying exclusions.

## Helper Diagnostics

`helper_diagnostics.json` is versioned by `version="1.0"` and must conform to `schemas/helper_diagnostics.schema.json`.

Required contract fields:

- `status`: `PASS` or `FAIL`
- `errors`: deterministic string list
- `warnings`: deterministic string list
- `helper`: launch/runtime metadata
- `output`: whether BPMN output was written
- `runtime_target`: runtime-preservation target summary

If the helper does not emit diagnostics on success, the bridge writes a valid default payload.
If the helper emits invalid diagnostics, the bridge fails with `helper_invalid_output`.

## Rehydration Invariants

Before the final BPMN is accepted, the bridge compares the original input against `helper_output.bpmn` and hard-fails on any invariant breach.

Mandatory invariants:

- Semantic BPMN ID set is preserved for `process`, flow nodes, and `sequenceFlow`.
- If the input declares the Camunda or Zeebe runtime namespace, the output must still declare the same namespace URI.
- All `camunda:*` and `zeebe:*` runtime attributes present in the input must still be present in the output.
- All `camunda:*` and `zeebe:*` runtime extension elements present in the input must still be present in the output.

These are hard checks. The bridge does not silently accept lossy helper output.

## Deterministic Failure Codes

The bridge uses these failure codes:

- `projection_generation_failed`
- `helper_launch_failed`
- `helper_runtime_failed`
- `helper_invalid_output`
- `projection_rehydration_failed`
- `namespace_loss_detected`
- `extension_loss_detected`
- `id_mismatch_detected`

Failure-code intent:

- projection build/read/write failure: `projection_generation_failed`
- helper process could not be started: `helper_launch_failed`
- helper started but returned runtime failure or explicit `FAIL`: `helper_runtime_failed`
- helper output/diagnostics contract invalid: `helper_invalid_output`
- final copy/rehydration step failed after invariants passed: `projection_rehydration_failed`
- invariant-specific semantic breach: `namespace_loss_detected`, `extension_loss_detected`, `id_mismatch_detected`

## Acceptance Rule

Simple mode may continue only when:

- `projection_sidecar.json` matches the frozen sidecar schema
- `helper_diagnostics.json` matches the frozen diagnostics schema
- helper output exists and is parseable BPMN XML
- all rehydration invariants pass
