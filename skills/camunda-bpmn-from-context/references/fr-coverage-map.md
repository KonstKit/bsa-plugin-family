# FR Coverage Map

This table maps functional requirements to the plan surface, implementation artifacts, and acceptance checks.

## Coverage Table

| FR | Capability | Plan | Primary artifact(s) | Acceptance test(s) |
|---|---|---|---|---|
| FR-01 | Backend selection and simple orchestration | `plan_02`, `plan_05` | `scripts/run_bpmn_pipeline.py`, `scripts/validate_run_manifest.py`, `references/output-contract.md` | `scripts/test_run_bpmn_pipeline.py`, `scripts/test_validate_run_manifest.py` |
| FR-02 | Projection / rehydration contract | `plan_04`, `plan_17` | `references/simple_projection_contract.md`, `schemas/projection_sidecar.schema.json` | `scripts/test_projection_rehydration_contract.py` |
| FR-03 | Framing and preserve drift controls | `plan_07` | `scripts/apply_bpmn_layout_policy.py`, `references/layout-policy.md` | `scripts/test_apply_bpmn_layout_policy.py` |
| FR-04 | Label and route conflict resolution | `plan_08` | `scripts/apply_bpmn_layout_policy.py`, `schemas/typed_issue_targets.schema.json` | `scripts/test_apply_bpmn_layout_policy.py` |
| FR-05 | Canonical run manifest and linked report contract | `plan_13`, `plan_18` | `schemas/run_manifest.schema.json`, `schemas/linked_report.schema.json`, `references/run-manifest-schema.md` | `scripts/test_validate_run_manifest.py` |
| FR-06 | Self-contained offline preview MVP | `plan_11`, `plan_19` | `scripts/build_preview_artifacts.py`, `node_tooling/preview_assets/preview-app.js`, `node_tooling/preview_assets/preview-app.css` | `tests/preview/playwright_smoke.spec.ts`, `scripts/test_preview_artifacts.py` |
| FR-07 | Metadata summary and typed issue target model | `plan_12` | `schemas/typed_issue_targets.schema.json`, `references/preview-artifacts.md` | `scripts/test_preview_artifacts.py` |
| FR-08 | Fixture-backed acceptance matrix and CI gates | `plan_16`, `plan_20` | `scripts/engine_smoke_matrix.py`, `scripts/make_stripped_fixture.py`, `scripts/fixtures/fixture_inventory.json`, `scripts/fixtures/fixture_lineage.json` | `scripts/test_acceptance_matrix.py`, `scripts/test_make_stripped_fixture.py`, `scripts/test_engine_smoke_matrix.py` |
| FR-09 | Governance docs and release-phase boundaries | `plan_14`, `plan_15` | `references/release-phases.md`, `references/support-matrix.md`, `references/engine-smoke-hooks.md`, `SKILL.md` | `scripts/validate_governance_docs.py`, `scripts/test_acceptance_matrix.py` |

## Use

- Use this map when you need traceability from a feature request to a concrete acceptance surface.
- If a row does not have a matching acceptance test, treat the requirement as not release-gated yet.
- `plan_09` remains deferred and intentionally does not appear as a blocking row in this map.
