# Modeling Conventions

Use these conventions unless the source or the user requires something else.

## Evidence To BPMN Mapping

- Use `startEvent` for the process trigger.
- Use `endEvent` for materially different outcomes.
- Use `serviceTask` for automated/API/system actions.
- Use `userTask` when a human completes work in a task inbox.
- Use `manualTask` when a human action exists but is not tracked by a workflow engine.
- Use `callActivity` when the source clearly refers to a reusable called process.
- Use `subProcess` when a grouped block is helpful and the source supports that grouping.
- Use `exclusiveGateway` for mutually exclusive decisions.
- Use `parallelGateway` only when the source explicitly states simultaneous paths.
- Use `inclusiveGateway` only when one or more branches may be taken together.
- Use intermediate events for waits, messages, or timers only when evidence supports them.
- Use `boundaryEvent` when an exception or timeout attaches to an activity.
- Use event subprocess only when the source explicitly describes an interrupting or non-interrupting event-driven scope.
- Use multi-instance only when the source explicitly describes iteration over a collection, repeated approval, or parallel-for-each behavior.

## Camunda Runtime Target

- Always confirm the target runtime before generating engine-specific extensions:
  - `Camunda 7`
  - `Camunda 8`
  - `documentation-only BPMN`
- If the runtime is unknown, generate standards-compliant BPMN 2.0 XML first and state that engine-specific extensions were intentionally deferred.

## Engine-Specific Extension Rules

Use only one engine namespace per file.

| Concern | Camunda 7 | Camunda 8 |
|---|---|---|
| Namespace | `camunda:*` | `zeebe:*` |
| User assignment | `camunda:assignee`, `camunda:candidateUsers`, `camunda:candidateGroups` | `zeebe:userTask` with assignment / candidate metadata |
| Forms | `camunda:formKey` | `zeebe:formDefinition` |
| Service execution | `camunda:type`, `camunda:delegateExpression`, or external-task conventions | `zeebe:taskDefinition type="..." retries="..."` |
| Job worker semantics | implementation-specific in C7 | explicit Zeebe worker/job type semantics |

- Do not mix `camunda:*` and `zeebe:*` in the same deliverable.
- If the source does not provide enough runtime detail, keep the BPMN structural and documentation-first.

## Modeling Mode

- `AS-IS`
  - preserve real operational behavior, including manual workarounds and human escalations
  - do not “clean up” the process into an aspirational design
- `TO-BE`
  - model the target-state process only
  - warn when `manualTask` remains without explicit justification
  - prefer deployable or near-deployable semantics when the runtime target is known

## Detail Levels

- `overview`
  - target roughly 5-10 modeled elements
  - collapse operational detail into subprocesses or call activities
- `detailed`
  - target roughly 10-30 modeled elements
  - include the main branches, escalations, and critical integrations
- `technical`
  - target roughly 25-60 modeled elements per diagram
  - include explicit waits, failure handling, runtime-relevant task types, and decomposition into subprocesses where needed

## Collaboration And Participants

- Use `collaboration` with `participant` when the flow crosses organizational or major system boundaries.
- Use `messageFlow` between participants when communication itself is meaningful.
- Keep `sequenceFlow` inside a single process only.
- Preserve participant bounds and message-flow DI when editing an existing collaboration diagram.
- Treat `messageFlow` BPMNDI as `basic greenfield support`, not as a polished collaboration layouter. Review larger diagrams manually.
- Treat lane membership as both a placement hint and a source for basic lane DI generation, but do not overclaim visual perfection on dense diagrams.

## Extended Elements

- Use message events when a process waits for or emits a business message.
- Use timer events for SLA expiry, scheduled waits, or callback windows.
- Use signal events only when the source explicitly describes broadcast-style behavior.
- Use `dataObjectReference` or `dataStoreReference` only when the artifact is important to understanding the process.
- Use text annotations sparingly and only for context that should not become executable flow logic.
- For artifacts and associations, distinguish `basic heuristic DI generation` from `fully semantics-aware DI generation`. The current skill provides the former, not the latter.
- For multi-instance tasks or subprocesses, keep the BPMN marker semantics explicit and review loop cardinality / collection metadata manually.
- For event subprocesses, keep the trigger explicit and treat runtime behavior as `manual review required` unless the source is implementation-grade.

## Naming

- Use stable descriptive IDs such as `Task_CreateSalesforceTask` or `Gateway_CallerWantsAgent`.
- Name gateways as questions when possible.
- Name end events by outcome, not by generic completion words alone.

## Drafting Order

1. Main flow
2. Alternate success paths
3. Failure and escalation paths
4. Collaboration boundaries and message flows
5. Data / timer / message details only if evidenced

## Review Checklist

Check these before delivery:

- every gateway has clear meaning
- every branch rejoins or terminates intentionally
- every major outcome has an end event
- message flows are only used across participants
- no undocumented logic was invented
- XML matches the documented claim level: BPMN 2.0 XML with only the explicitly supported Camunda 7/8 extensions
- runtime-specific extensions match the confirmed engine version
- unsupported or partial-support constructs were surfaced explicitly
- the supported scope does not imply full BPMN coverage or production readiness
- BPMNDI remains readable and locally stable

## Default Output

- Produce BPMN 2.0 XML with BPMNDI.
- Default to `isExecutable="false"` unless execution semantics are requested.
- Preserve an existing readable BPMNDI layout when only local fixes are needed.
- Default claim: `BPMN 2.0 XML with documented Camunda 7/8 extension support`, not blanket “fully Camunda-compatible deployment XML”.
