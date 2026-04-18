# Run Manifest Schema

This document defines the current canonical `run_manifest.json` contract implemented by the package.

## Purpose

The manifest is the only authoritative index for a run bundle. Linked reports are attached through `artifacts`, but they do not duplicate backend choice or fallback semantics.

## Required Top-Level Fields

- `manifest_schema_version`
- `linked_report_schema_version`
- `build_version`
- `skill_version`
- `runtime_target`
- `requested_mode`
- `logic_only`
- `preserve_existing_di`
- `full_relayout`
- `eligibility_class`
- `eligibility_reasons`
- `scenario_id`
- `fixture_id`
- `traceability_count`
- `assumptions_count`
- `initial_backend`
- `final_backend`
- `fallback_happened`
- `semantic_status`
- `layout_status`
- `layout_summary`
- `preview_status`
- `layout_hint_source`
- `hint_applied`
- `artifacts`

Optional top-level fields:

- `layout_bypass`
- `fallback_reason_code`
- `preview_summary`

## Value Vocabulary

Backend vocabulary:

- `native`
- `simple`
- `none`

Status vocabulary:

- top-level `semantic_status`: `PASS | FAIL`
- top-level `layout_status`: `PASS | FAIL | SKIPPED`
- `layout_summary.final_status`: `PASS | FAIL | SKIPPED`
- top-level `preview_status`: `PASS | FAIL | SKIPPED`
- top-level `hint_applied`: `true | false`
- linked artifact `status`: `PASS | FAIL | SKIPPED`

Presence vocabulary:

- `present`
- `skipped`
- `not_applicable`

## Context Fields

Runtime identity fields:

- `build_version`
- `skill_version`
- `runtime_target`

Traceability fields:

- `scenario_id`: string or null
- `fixture_id`: string or null
- `traceability_count`: integer, must be `>= 0`
- `assumptions_count`: integer, must be `>= 0`

## Artifact Reference Shape

Every artifact record uses this shape:

- `report_kind`
- `presence`
- `status`
- `schema_version`
- `path` when `presence = present`
- `hash` when `presence = present`

`path` and `hash` are forbidden when `presence` is `skipped` or `not_applicable`.

## Canonical Artifact Keys

The manifest reserves these exact keys:

- `backend_selection`
- `semantic_report`
- `layout_report`
- `preview_report`
- `human_summary`
- `typed_issue_targets`

Canonical filenames:

- `backend_selection.json`
- `semantic_report.json`
- `layout_report.md`
- `preview_report.json`
- `human_summary.md`
- `typed_issue_targets.json`

`typed_issue_targets` is the canonical name for typed issue target output across schema, docs, and runtime.

## Required Presence Rules

- `backend_selection` must be `present`
- `semantic_report` must be `present`
- `human_summary` must be `present`
- `layout_report` must be `present` whenever `layout_status != SKIPPED`
- `preview_report` must be `present` whenever `preview_status != SKIPPED`
- `typed_issue_targets` may be `present`, `skipped`, or `not_applicable`

## Schema Version Rules

Current contract versions:

- `manifest_schema_version = "2"`
- `linked_report_schema_version = "2"`

Only version `2` is currently accepted for both fields. All artifact `schema_version` values must equal `linked_report_schema_version`.

## Cross-Field Rules

- `layout_status = SKIPPED` only when `logic_only = true` or `layout_bypass = true`
- `layout_bypass = true` requires `layout_status = SKIPPED`
- `layout_hint_source` must always be present
- `hint_applied = true` requires `layout_hint_source` to be non-`none`
- `hint_applied = true` is invalid when `layout_status = SKIPPED`
- `layout_summary.final_status` must match `layout_status` for `PASS|FAIL` runs
- `layout_summary.warning_issue_count + layout_summary.error_issue_count <= layout_summary.typed_issue_count`
- `layout_summary.advisory_only = true` requires `layout_status = PASS` and `error_issue_count = 0`
- optional readability fields (`diagram_width_px`, `diagram_height_px`, `aspect_ratio_x100`, `max_depth_columns`, `max_edge_span_columns`, `consecutive_gateway_chain_length`, `readability_violations`) must be non-negative integers when present
- `layout_summary.layout_requires_decomposition = true` requires `layout_summary.readability_violations > 0`
- `initial_backend = none` only when `logic_only = true`
- `final_backend = none` only when `logic_only = true`
- `final_backend = none` requires `layout_status = SKIPPED`
- `final_backend = none` requires `preview_status = SKIPPED`
- `fallback_happened = true` requires non-empty `fallback_reason_code`
- `fallback_happened = false` forbids non-empty `fallback_reason_code`
- `fallback_happened = true` requires either:
  - `initial_backend = simple` and `final_backend = native`
  - `initial_backend = native`, `final_backend = native`, and `fallback_reason_code = native_preserve_degraded_to_greenfield`
- `fallback_happened = false` requires `initial_backend = final_backend`
- supported backend transitions are `none -> none`, `native -> native`, `simple -> simple`, and `simple -> native`
- artifact `report_kind` must match the artifact key it is stored under
- artifact `status` must match the corresponding manifest status when the artifact is `present`
- `backend_selection.status` and `human_summary.status` must reflect the terminal run outcome

## Validation Surface

Executable validation uses:

- `schemas/run_manifest.schema.json`
- `schemas/linked_report.schema.json`
- `scripts/validate_run_manifest.py`

Human-readable summary output is produced by `scripts/run_bpmn_pipeline.py` from the manifest only.
