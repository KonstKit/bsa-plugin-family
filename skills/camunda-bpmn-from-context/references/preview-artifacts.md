# Preview Artifacts

## Packaging Model

The preview MVP emits a filesystem-safe package with this shape:

- `index.html`
- `assets/preview-app.js`
- `assets/preview-app.css`
- `assets/vendor/*`

The package is built from `run_manifest.json` only. The builder resolves all required linked artifacts through manifest references, validates manifest integrity first, validates linked artifact hashes, then resolves the final BPMN XML path through `backend_selection.json` based on `final_backend`.

The embedded BPMN payload is integrity-bound in two steps:

- `run_manifest.json` binds `backend_selection.json` by path and sha256
- `backend_selection.json` binds the final BPMN file by `output_bpmn_path` plus `output_bpmn_hash`

The preview builder verifies both links before embedding any XML.

## Metadata Summary Panel

`index.html` now embeds a metadata summary payload derived from manifest fields only. The runtime renders a dedicated metadata panel with:

- run identity (`build_version`, `skill_version`, `runtime_target`)
- schema versions (`manifest_schema_version`, `linked_report_schema_version`)
- fixture/scenario context (`fixture_id`, `scenario_id`)
- traceability counters (`traceability_count`, `assumptions_count`)
- fallback reason and typed-issue count
- layout quality summary (`layout_final_mode`, `layout_profile_family`, `warning_issue_count`, `error_issue_count`, `advisory_only`)
- readability summary (`diagram_width_px`, `diagram_height_px`, `aspect_ratio_x100`, `max_depth_columns`, `max_edge_span_columns`, `consecutive_gateway_chain_length`, `readability_violations`, `layout_requires_decomposition`)
- flow/DI counters (`sequence_flow_count`, `bpmn_edge_count`, `bpmn_shape_count`)

No side-channel payload is used for metadata rendering.

## Embedded Payloads

`index.html` contains inline payload blocks for:

- final BPMN XML
- manifest summary payload
- metadata summary payload
- report summary payload
- typed issue targets payload
- version payload with `skill_version`, `preview_schema_version`, and `build_timestamp`

`build_timestamp` is deterministic. The builder does not use wall-clock time when rendering the preview package. Current fallback value is the stable string `not-provided` when no manifest-provided source exists.

The viewer runtime is read-only. It imports the embedded XML into a local BPMN viewer bundle and does not mutate the model.

## Typed Issue Targets Contract

Preview build emits `typed_issue_targets.json` in the package root and validates it against:

- `schemas/typed_issue_targets.schema.json`

Current generation source is manifest-linked `layout_report.md` issue lines (`- issue: ...`) produced by layout policy reporting. If no compatible issue lines are present, the payload remains valid with an empty `items` list and zero counts.

Typed issue target classes:

- `shape`
- `edge`
- `label`
- `pair`
- `global`

Required issue fields:

- `target_type`
- `element_id`
- `secondary_element_id`
- `label_role`
- `bbox`
- `severity`
- `code`
- `message`

Optional extension fields:

- `issue_id`
- `source_report`
- `source_rule`

Highlight policy marker is explicit in payload metadata:

- canvas-capable classes are `shape`, `edge`, `label`, `pair`
- `global` remains text-only guidance

## Browser Strategy

The runtime uses local assets only. No CDN or remote stylesheet/script references are allowed.

Viewer behavior in MVP:

- adaptive initial zoom on load:
  - default path keeps fit-to-viewport
  - very-wide diagrams (high aspect ratio / width budget breach) start from readable zoom instead of full fit
- basic zoom controls
- basic pan controls
- reset-to-fit control
- viewer-only mode label and visible version stamp
- runtime graph counters exposed via `window.__previewRuntime`:
  - `sequenceFlowCount`
  - `renderedConnectionCount`
  - `shapeCount`
  - `connectionLayerConsistent`
  - `expectedConnectionCount`
  - `expectedSequenceFlowCount`

Playwright project selection is env-driven through `PREVIEW_PLAYWRIGHT_PROJECTS`:

- omitted value defaults to `chromium`
- `preview:smoke` pins `chromium` explicitly for PR gates
- `preview:smoke:matrix` expands to `chromium,firefox,webkit` for nightly verification
- both commands resolve `tests/preview/playwright.config.ts` explicitly so project selection stays deterministic

Fail-fast rules:

- if `PREVIEW_PLAYWRIGHT_PROJECTS` is set but empty, smoke fails
- if the value includes unsupported browser names, smoke fails
- supported values are `chromium`, `firefox`, and `webkit`

## Offline Guard

`scripts/build_preview_artifacts.py` performs an explicit runtime audit after generating the package. The audit rejects:

- external `src` / `href` references in HTML
- external `iframe src` references in HTML
- external `srcset` references in HTML
- external `url()` / `@import` references in CSS
- any external `http://` or `https://` URL literal in runtime JavaScript
- runtime network or navigation primitives such as `fetch()`, `XMLHttpRequest`, `navigator.sendBeacon()`, `new Image().src`, `location.href`, `location.assign(...)`, or `window.open(...)` in generated JavaScript

If any of those conditions are detected, the preview build fails.

## Deferred Scope (Phase 5)

The following features are intentionally deferred and must not be inferred from MVP payload availability:

- interactive canvas highlight behavior for typed issue targets
- multi-diagram package index and navigation UI

Current runtime only renders textual typed-issue summaries and metadata summaries.

## Smoke Strategy

`tests/preview/playwright_smoke.spec.ts` is the Chromium smoke scaffold for:

- offline file open
- BPMN import success
- fit-to-viewport behavior
- zoom / pan / reset controls
- version-stamp visibility
- connection-layer visibility (`sequenceFlowCount > 0` and `renderedConnectionCount > 0` for flow fixtures)
- runtime count consistency (`connectionLayerConsistent=true` for flow fixtures)
- no external network requests

Preview PASS requires rendered connection layer, not only successful XML import.

This smoke is intended to run against a package already produced by `build_preview_artifacts.py`.

`PREVIEW_DIR` is required for smoke execution. Missing `PREVIEW_DIR` is treated as a hard failure, not a skipped run.

## Rollback Guidance

If mandatory Chromium smoke fails in PR or release-candidate flow:

- treat the preview package as non-verified
- keep the core manifest / BPMN pipeline unchanged
- disable preview promotion until the Chromium smoke gate passes again

Nightly browser matrix failures are informative unless they also break the mandatory Chromium path.
