# Deployment Readiness

Use this reference when the user asks whether a BPMN artifact is merely documented, review-ready, or truly deployable.

## Readiness Levels

- `documentation draft`
  - BPMN 2.0 structure is present
  - assumptions and traceability are explicit
  - no deployability claim is allowed

- `review-ready BPMN`
  - `xmllint --noout` passes
  - semantic validator passes for the selected runtime profile
  - validator-enforced subset rules and emitted warnings are disclosed honestly in the delivery note
  - layout checks pass when BPMNDI is included
  - open questions and partial-support constructs are disclosed

- `runtime-profiled BPMN`
  - the file targets exactly one runtime profile: `documentation-only`, `Camunda 7`, or `Camunda 8`
  - runtime-specific extensions match that profile
  - the file passes the currently implemented runtime-aware validator subset for that profile (runtime proof only, not full parity proof)
  - support-matrix limitations are surfaced in the final answer

- `deployable Camunda 7`
  - all `review-ready BPMN` checks pass
  - `engine_smoke_bpmn` profile is `7` and returns `status: PASS`
  - import, deploy, and process smoke steps are executed and pass

- `deployable Camunda 8`
  - all `review-ready BPMN` checks pass
  - `engine_smoke_bpmn` profile is `8` and returns `status: PASS`
  - import, deploy, and process smoke steps are executed and pass

## Claim Rules

- Do not claim `deployable` from static XML, lint, validator, or layout results alone.
- Do not claim `deployable` unless engine-level import or deploy checks have actually been run.
- If engine-level checks were not run, say `review-ready` or `runtime-profiled`, not `deployable`.
- Run [scripts/engine_smoke_bpmn.py](../scripts/engine_smoke_bpmn.py) when you need an operational record of import/deploy/process-smoke verification.
- Use [scripts/engine_smoke_matrix.py](../scripts/engine_smoke_matrix.py) for repeatable local/CI profile runs across C7/C8 fixtures and status expectations (`happy` expects `PASS`, `negative` expects `NOT_VERIFIED`).
- Treat `SKIPPED`, `MISCONFIGURED`, and `NOT_VERIFIED` engine smoke as `not verified`, never as `passed`.
- Treat anything other than `PASS` as `not verified` for deployability.
- Treat semantic-validator success as evidence for the documented subset only; it is not proof of full BPMN notation coverage or full Camunda runtime parity.

## Minimum External Checks

When deployability matters, require at least:

1. model import/open round-trip in the target modeler or runtime tooling
2. deploy validation in the target Camunda environment
3. a minimal process execution smoke test for the critical path

## Engine Smoke Conventions

- Configure all three steps together: import, deploy, and process smoke.
- If the environment is unavailable, record `SKIPPED` and keep readiness below `deployable`.
- If any configured step fails, readiness stays `not verified` unless final status is `PASS`.
- Keep readiness below `deployable` when engine smoke status is `SKIPPED`, `MISCONFIGURED`, or `NOT_VERIFIED`.
- Prefer deterministic command wiring through `--shell`, `BPMN_SMOKE_*_CMD`, and placeholder/env inputs rather than hard-coded machine-specific paths.
- Prefer deterministic matrix runs in CI with:
  - `python scripts/engine_smoke_matrix.py --profiles both --suite happy --report-dir <artifacts> --import-cmd ... --deploy-cmd ... --process-test-cmd ...`
  - plus a separate negative suite:
  - `python scripts/engine_smoke_matrix.py --profiles both --suite negative --report-dir <artifacts> --import-cmd ... --process-test-cmd ...`

## Scope Caveat

- This skill is intentionally scoped to a documented BPMN/Camunda-aware subset, not full BPMN 2.0 coverage.
- Even with stricter validator rules for timers, message/signal events, and C7/C8 task metadata, static validation remains weaker than real engine behavior.
- A `runtime-profiled` claim is explicit runtime proof for the documented subset only.
- A `100% ready` claim is only defensible relative to the documented subset, and only when the required engine-smoke proof path returns `PASS`.
- Full-runtime-parity claims are out of scope for this package and must be treated as separate engineering scope.
