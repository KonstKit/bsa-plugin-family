# Release Phases

This document defines the phase boundaries used by the acceptance harness and governance checks.

## Phase 0-4 Critical Path

- Phase 0: contract freeze, backend selection, and orchestration baseline.
- Phase 1: projection / rehydration bridge and fallback chain behavior.
- Phase 2: native layout consistency, framing, and conflict resolution.
- Phase 3: output contract, metadata summary, and offline preview MVP.
- Phase 4: fixture-backed acceptance matrix, lineage, and CI gates.

The critical path maps to:

- `plan_02`, `plan_03`, `plan_04`, `plan_05`, `plan_06`
- `plan_07`, `plan_08`, `plan_10`, `plan_11`, `plan_12`, `plan_13`
- `plan_14`, `plan_15`, `plan_16`, `plan_17`, `plan_18`, `plan_19`, `plan_20`

## Phase 5 Deferred Optional Enhancements

- `plan_09` is deferred optional hint ingestion.
- Highlight / package-index work stays out of the release gate until the Phase 0-4 path is stable.
- Optional enhancements may be implemented after release approval, but they do not block `release_candidate`.

## Unified Release Gate

The release decision is made in one pass from these required surfaces:

- acceptance matrix
- manifest schema validation
- preview smoke
- governance docs validation
- preview_report artifact
- typed_issue_targets artifact
- usable original fixtures are runtime-tested in native-preserve path; partial-DI originals route through simple/direct or fallback paths per selector output

Profile rule:

- `pr` and `nightly` report governance status but do not fail the existing pass path unless governance is explicitly required.
- `release_candidate` requires governance to pass together with the other required gates.

The acceptance summary writes a single `matrix_summary.json` with the gate outcome and the per-surface details needed for audit.
