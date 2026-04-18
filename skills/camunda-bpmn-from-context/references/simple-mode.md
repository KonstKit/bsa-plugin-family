# Simple Mode

Simple mode is the optional hybrid path that routes through projection + helper + rehydration before final semantic checks.

## Inputs

- `requested_mode`
- `logic_only`
- `preserve_existing_di`
- `full_relayout`
- selector facts extracted from BPMN constructs

## Routing Semantics

- `logic_only=true` bypasses layout and preview.
- Usable existing BPMN DI (`di_quality=usable_di`) defaults to native-preserve when `full_relayout=false`.
- Partial DI (`di_quality=partial_di`) is tracked separately and does not imply preserve defaults.
- `preserve_existing_di=true` forces native unless `full_relayout=true`.
- Hard exclusions force native.
- If simple is selected but helper is unavailable, orchestrator emits `simple_helper_unavailable_forced_native` and routes to native.
- Simple helper output may be shape-only or partial DI. Simple `PASS` is allowed only after Python post-process confirms complete edge DI for all semantic `sequenceFlow` elements.
- Simple post-process uses dedicated profile family (`simple_postprocess_refine`, `simple_postprocess_repair`, `simple_postprocess_greenfield`) and reports internal final mode as `simple_postprocess_*` (not `native_*`).
- `full_relayout=true` is the only supported path that allows existing-DI inputs to route through simple mode.
- Runtime quality is surfaced in manifest `layout_summary` (`final_mode`, severity counts, advisory flag, readability counters, `layout_requires_decomposition`) so gate decisions do not require markdown parsing.

See:

- [selector_decision_table.md](selector_decision_table.md)
- [selector-reason-codes.md](selector-reason-codes.md)
- [simple_projection_contract.md](simple_projection_contract.md)

## Hard Exclusions

Simple mode is excluded for:

- multi-participant collaboration
- `messageFlow`
- `textAnnotation`
- `association`
- `complexGateway`
- `group`
- `boundaryEvent`
- `eventSubProcess`
- expanded subprocess

## Helper Contract

Bridge-managed artifacts:

- `helper_input.bpmn`
- `projection_sidecar.json`
- `helper_output.bpmn`
- `helper_diagnostics.json`

`helper_diagnostics.json` must include DI completeness counters:

- `sequence_flow_count`
- `bpmn_shape_count`
- `bpmn_edge_count`
- `edge_without_two_waypoints_count`
- `edge_di_complete`

Failure codes and invariant checks are frozen in [simple_projection_contract.md](simple_projection_contract.md).
