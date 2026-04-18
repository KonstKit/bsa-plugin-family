---
name: camunda-bpmn-from-context
description: Generate documentation-first BPMN 2.0 XML with documented Camunda 7 or Camunda 8 extension support and readable BPMNDI from attached documents, PDFs, transcripts, meeting notes, screenshots, and business-process descriptions. Use when Codex needs to infer a workflow, ask clarifying questions, produce a new `.bpmn` file, review or fix an existing BPMN diagram, or validate BPMN layout/readability before delivery.
---

# Camunda BPMN From Context

Build BPMN diagrams from evidence, not guesswork. Extract actors, systems, tasks, gateways, exception paths, and outcomes from the provided context, then generate documentation-first BPMN 2.0 XML with readable BPMNDI and only the Camunda runtime extensions that are explicitly documented and supported by the confirmed target runtime.

## Workflow

1. Inventory the sources.
- Read only the artifacts relevant to the requested process.
- Extract text from PDFs, transcripts, and descriptions first.
- Build a working map of:
  - trigger / start event
  - actors / pools / lanes / participants
  - systems and integrations
  - primary flow
  - alternate paths
  - exception paths
  - end states
  - unresolved gaps
- If an existing `.bpmn` file is provided, treat its BPMNDI geometry as the baseline to preserve.
- If the process clearly spans multiple independent actors or organizations, model `collaboration` / `participant` boundaries instead of flattening everything into one process.

2. Ask clarifying questions proactively.
- Before writing BPMN, ask 3-7 focused questions unless the sources already resolve the ambiguity.
- Prioritize only questions that change the structure of the diagram:
  - process boundaries
  - start trigger
  - end outcomes
  - actor / lane ownership
  - AS-IS vs TO-BE modeling mode
  - required level of detail: overview / detailed / technical
  - target runtime: Camunda 7, Camunda 8, or documentation-only BPMN
  - automation vs manual or user work
  - undocumented retries, waits, timers, or escalations
  - executable vs documentation-only BPMN
  - desired level of detail and output file path
- Ask short, concrete questions.
- If the user does not answer, continue only with explicit assumptions.
- If the process appears large or highly ambiguous, confirm the intended scope before generating a file.

3. Model the process.
- Model the happy path first, then alternate paths, then exceptions.
- Create explicit end events for materially different outcomes.
- Give gateways question-style names and name outgoing conditions when evidence supports them.
- Do not invent undocumented integrations, timers, or subprocesses.
- Prefer stable descriptive IDs.
- Default to `isExecutable="false"` unless execution semantics are explicitly requested or clearly supported by the source.
- If the Camunda runtime is not confirmed, generate documentation BPMN first and state that runtime-specific extensions are deferred.
- Respect the requested modeling mode:
  - `AS-IS`: preserve real manual steps, workarounds, and operational handoffs.
  - `TO-BE`: prefer target-state automation and warn when manual work remains without justification.
- Respect the requested detail level:
  - `overview`: roughly 5-10 modeled elements
  - `detailed`: roughly 10-30 modeled elements
  - `technical`: roughly 25-60 modeled elements or explicit decomposition into subprocesses / call activities
- Use collaboration and participant shapes when handoffs cross organizational or system boundaries and message flow is semantically important.

4. Produce the deliverable.
- Write real BPMN 2.0 XML, not pseudo-BPMN.
- Include BPMNDI coordinates unless the user explicitly asks for logic-only XML.
- Validate XML with `xmllint --noout`.
- Run [scripts/semantic_validate_bpmn.py](scripts/semantic_validate_bpmn.py) for BPMN semantic validation before delivery.
- If layout/readability matters, run [scripts/apply_bpmn_layout_policy.py](scripts/apply_bpmn_layout_policy.py).
- If the user asks for deployability or runtime proof, run [scripts/engine_smoke_bpmn.py](scripts/engine_smoke_bpmn.py) with real import/deploy/process-smoke commands for the selected Camunda target.
- For repeatable local/CI evidence across fixtures, run [scripts/engine_smoke_matrix.py](scripts/engine_smoke_matrix.py) and archive its summary report together with per-run engine smoke reports.
- If a Camunda runtime was confirmed, keep runtime extensions consistent with that version only:
  - Camunda 7 -> `camunda:*`
  - Camunda 8 -> `zeebe:*`
- Report assumptions, unresolved questions, and the output file path.

5. Review and fix mode.
- Follow this order:
  1. load the existing `.bpmn` and extract the current element map
  2. compare the existing graph against the source context
  3. build a gap list: missing branches, wrong task/event choice, ambiguous gateways, broken outcomes, readability issues
  4. describe the intended changes briefly before editing if the gaps are structural
  5. apply the smallest graph change that resolves the gap
  6. preserve existing geometry when local fixes are sufficient
  7. rerun semantic validation and layout checks
- Prioritize:
  - missing branches
  - ambiguous gateways
  - wrong task/event choice
  - unreadable routing
  - label overlap
  - avoidable global layout shifts

## References

- Read [references/intake-and-questions.md](references/intake-and-questions.md) when the source material is incomplete, conflicting, or underspecified.
- Read [references/modeling-conventions.md](references/modeling-conventions.md) for BPMN element mapping, naming, and review criteria.
- Read [references/support-matrix.md](references/support-matrix.md) to confirm the construct-specific status per axis: `yes`, `partial`, `no`, `preserve-only`, or `n/a`.
- Read [references/traceability-contract.md](references/traceability-contract.md) when the BPMN must remain auditable back to documents, transcripts, or workshop notes.
- Read [references/traceability-table-template.md](references/traceability-table-template.md) when you need a ready-to-use sidecar format.
- Read [references/review-mode.md](references/review-mode.md) for the gap-analysis workflow when editing an existing BPMN file.
- Read [references/layout-policy.md](references/layout-policy.md) if you need to understand or adjust the post-generation layout checks.
- Read [references/simple-mode.md](references/simple-mode.md) for simple-mode entry conditions, exclusions, helper contract, and fallback semantics.
- Read [references/selector_decision_table.md](references/selector_decision_table.md) for deterministic selector precedence and mode truth-table coverage.
- Read [references/selector-reason-codes.md](references/selector-reason-codes.md) for canonical selector/fallback reason-code vocabulary.
- Read [references/acceptance-fixtures.md](references/acceptance-fixtures.md) for fixture IDs and expected routing classes.
- Read [references/release-phases.md](references/release-phases.md) when you need the current phase boundaries and release-gate scope.
- Read [references/fr-coverage-map.md](references/fr-coverage-map.md) when you need FR-to-plan-to-artifact traceability.
- Read [references/engine-smoke-hooks.md](references/engine-smoke-hooks.md) when you need the acceptance matrix or unified release-gate invocation.
- Read [references/deployment-readiness.md](references/deployment-readiness.md) when the user asks whether the BPMN is only documented, review-ready, runtime-profiled, or actually deployable.

## Output Contract

- Deliver a `.bpmn` file.
- Keep a short assumption block in the final response.
- Distinguish evidenced behavior from assumed behavior.
- If the process is sourced from multiple artifacts or will be reviewed as a BA/SA deliverable, include a compact traceability table or sidecar note.
- If the diagram is projected to exceed roughly 40-50 modeled elements, confirm whether the user wants one diagram or a decomposition.
- Do not overclaim deployability:
  - say `BPMN 2.0 XML with documented Camunda 7/8 extension support`
  - do not imply full BPMN coverage or full engine coverage for unsupported constructs
- Do not call the output `deployable` unless engine-level import or deploy checks have actually been run.
- Static XML lint, semantic validation, and layout checks are not a substitute for engine-level verification.
- Distinguish `greenfield generation` from `preserve-existing` support whenever the support matrix says `preserve-only`.
- If the source remains too ambiguous for safe modeling, stop after the clarifying questions instead of inventing process logic.
- If the runtime target, modeling mode, or detail level is still unknown, state the fallback assumption explicitly in the final response.

## Intentional Boundaries

- This skill supports a documented BPMN subset for documentation-first and review/fix workflows. It does not claim full BPMN 2.0 notation coverage.
- This skill is Camunda-aware, not a substitute for full Camunda Modeler/runtime parity.
- Full-BPMN and full-runtime-parity requests are out of scope for this skill package and must be handled as scope-split work, not as implicit promises.
- Use the support matrix to decide whether a construct is safe for greenfield generation, review-required, or preserve-only.
