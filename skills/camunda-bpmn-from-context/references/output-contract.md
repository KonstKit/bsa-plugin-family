# Output Contract

`run_manifest.json` is the canonical index for every run bundle. Linked artifacts are referenced from `artifacts` and never redefine backend selection, fallback reason, or terminal pipeline semantics.

## Canonical Top-Level Fields

The manifest emits these contract fields for every run:

- `manifest_schema_version`
- `linked_report_schema_version`
- `build_version`
- `skill_version`
- `runtime_target`
- `requested_mode`
- `logic_only`
- `preserve_existing_di`
- `full_relayout`
- `layout_bypass`
- `eligibility_class`
- `eligibility_reasons`
- `scenario_id`
- `fixture_id`
- `traceability_count`
- `assumptions_count`
- `initial_backend`
- `final_backend`
- `fallback_happened`
- `fallback_reason_code`
- `semantic_status`
- `layout_status`
- `layout_summary`
- `preview_status`
- `layout_hint_source`
- `hint_applied`
- `artifacts`

Backend and fallback remain authoritative only at the top level:

- backend enums live in `initial_backend` and `final_backend`
- fallback semantics live in `fallback_happened` and `fallback_reason_code`
- linked artifacts expose only their own `presence`, `status`, and reference metadata

## Schema Version Policy

Current runtime defaults are:

- `manifest_schema_version = "2"`
- `linked_report_schema_version = "2"`

Only schema version `2` is currently supported for both fields. Every artifact record also carries `schema_version`, and the validator requires it to match `linked_report_schema_version`.

## Linked Artifact Contract

Each `artifacts.*` entry is a linked report reference with these fields:

- `report_kind`
- `presence`: `present | skipped | not_applicable`
- `status`: `PASS | FAIL | SKIPPED`
- `schema_version`
- `path` only when `presence = present`
- `hash` only when `presence = present`

Hash policy:

- sha256 only
- lowercase hex only
- 64 characters exactly

Canonical artifact keys and filenames:

- `backend_selection` -> `backend_selection.json`
- `semantic_report` -> `semantic_report.json`
- `layout_report` -> `layout_report.md`
- `preview_report` -> `preview_report.json`
- `human_summary` -> `human_summary.md`
- `typed_issue_targets` -> `typed_issue_targets.json`

Current mandatory-present artifacts:

- `backend_selection`
- `semantic_report`
- `human_summary`

Current conditional artifacts:

- `layout_report`
- `preview_report`
- `typed_issue_targets`

`preview_report.json` includes technical counters used by smoke and review gates:

- `preview_import_ok`
- `sequence_flow_count`
- `bpmn_edge_count`
- `typed_issue_target_count`
- `final_bpmn_hash`
- `layout_final_mode`
- `warning_issue_count`
- `error_issue_count`
- `advisory_only`

The preview runtime mirrors these counters through `window.__previewRuntime` and adds a connection-layer consistency flag so runtime smoke can compare rendered connections to manifest-derived edge counts.

`typed_issue_targets` is the canonical artifact key and canonical filename for plan_12 issue-target output. Do not rename it to alternate aliases.

## Cross-Field Rules

The validator enforces these contract rules:

- `layout_status = SKIPPED` only when `logic_only = true` or `layout_bypass = true`
- `layout_bypass = true` requires `layout_status = SKIPPED`
- `layout_hint_source` is required for every manifest
- `hint_applied = true` requires `layout_hint_source != "none"`
- `hint_applied = true` is invalid when `layout_status = SKIPPED`
- `layout_summary.final_status` must match `layout_status` for `PASS|FAIL` runs
- `layout_summary` is the machine-readable quality signal and includes:
  - `final_mode`
  - `layout_profile_family`
  - typed issue severity counters
  - budget violation counters
  - readability counters (`diagram_width_px`, `diagram_height_px`, `aspect_ratio_x100`, `max_depth_columns`, `max_edge_span_columns`, `consecutive_gateway_chain_length`)
  - `readability_violations`
  - `layout_requires_decomposition`
  - `advisory_only`
- `initial_backend = none` and `final_backend = none` are allowed only when `logic_only = true`
- `final_backend = none` also requires `layout_status = SKIPPED` and `preview_status = SKIPPED`
- `fallback_happened = true` requires non-empty `fallback_reason_code`
- `fallback_happened = false` requires `fallback_reason_code` to be absent, null, or empty
- `fallback_happened = true` is valid for:
  - runtime transition `simple -> native`
  - runtime preserve degradation `native -> native` with `fallback_reason_code = native_preserve_degraded_to_greenfield`
- `fallback_happened = false` requires `initial_backend = final_backend`
- unsupported backend transitions such as `native -> simple` are rejected
- `backend_selection`, `semantic_report`, and `human_summary` must be `present`
- if `semantic_status`, `layout_status`, or `preview_status` is not `SKIPPED`, the matching artifact must be `present`
- artifact `status` must match the corresponding top-level status when the artifact is `present`
- artifact `schema_version` must match `linked_report_schema_version`
- preserve defaults are inferred only from usable DI; partial DI is tracked separately and must not be treated as preserve-ready input

Simple-postprocess completeness contract:

- simple `PASS` is valid only when post-process output has complete edge DI for semantic `sequenceFlow`
- helper/post-process diagnostics must publish DI completeness counters (`sequence_flow_count`, `bpmn_edge_count`, `edge_without_two_waypoints_count`, `edge_di_complete`)

## Summary Renderer

`human_summary.md` is a manifest-derived view only. The renderer consumes manifest fields and manifest-linked artifact references; it does not read backend-selection runtime state directly.

The summary currently renders:

- schema version and runtime identity fields
- backend, fallback, and terminal status fields
- scenario / fixture / counter context when present
- artifact presence and status lines for all non-summary linked artifacts

## Runtime Defaults

When the caller does not provide explicit context facts, the pipeline currently emits:

- `build_version = "unknown"`
- `skill_version = "camunda-bpmn-from-context"`
- `runtime_target = "camunda-bpmn-pipeline"`
- `scenario_id = null`
- `fixture_id = null`
- `traceability_count = 0`
- `assumptions_count = 0`

Use `references/run-manifest-schema.md` for the field dictionary and `schemas/` plus `scripts/validate_run_manifest.py` for executable validation.
