# BPMN Support Matrix

Use this file to decide whether a requested construct is safe to generate automatically.

## Reading The Matrix

Each construct is evaluated on separate axes:

- `structural XML`: the skill can generate the BPMN model element itself
- `BPMNDI greenfield`: the skill can generate new readable DI from scratch
- `BPMNDI preserve-existing`: the skill can keep and not destroy existing DI when it is already present
- `semantic validator`: the validator checks the construct beyond raw XML well-formedness
- `Camunda 7 executable`: the skill can validate or author runtime-relevant semantics for C7
- `Camunda 8 executable`: the skill can validate or author runtime-relevant semantics for C8

Status values:

- `yes`: implemented and reliable for the stated axis
- `partial`: implemented for a bounded subset; requires explicit runtime-oriented review before production claims
- `no`: do not rely on the skill for this axis
- `preserve-only`: retained when already present in source, but not generated from scratch
- `n/a`: the axis is not meaningful for the construct itself

## Orchestration Inputs And Hard Exclusions

The matrix is consumed after the orchestrator has already decided the runtime path. These inputs must be read before using the table:

- `requested_mode`
- `logic_only`
- `preserve_existing_di`
- `full_relayout`
- usable DI
- partial DI

Interpretation rules:

- `requested_mode=auto` selects the documented backend path, but it does not override construct support.
- `logic_only=true` is a top-level bypass: layout and preview are intentionally skipped.
- `preserve_existing_di=true` means existing BPMNDI should be retained when the construct is not `no` on the preserve-existing axis.
- native-preserve by default for usable existing DI inputs when `full_relayout=false`.
- partial DI does not imply preserve defaults.
- `full_relayout=true` opts into full redraw semantics and may discard preserve-only geometry.
- simple success requires post-process edge-DI completeness checks before final `PASS`.

Hard exclusions:

- `no` is a hard stop for greenfield generation and must not be claimed as supported.
- `preserve-only` means the construct may be kept when present, but it must not be described as greenfield-safe.
- A support claim is valid only when it matches the axis value in the table below.

These statuses describe this skill's documented support only. They do not imply full BPMN spec coverage or full Camunda runtime parity.

## Matrix

| Construct | Structural XML | BPMNDI Greenfield | BPMNDI Preserve-Existing | Semantic Validator | Camunda 7 Executable | Camunda 8 Executable | Notes |
|---|---|---|---|---|---|---|---|
| Basic flow nodes (`startEvent`, `endEvent`, core tasks, XOR/AND/OR gateways) | yes | yes | yes | yes | partial | partial | Structural coverage is broad; executable coverage still depends on task type and runtime metadata. |
| `task` / `undefinedTask` | yes | yes | yes | partial | no | no | Generic placeholder only; do not infer runtime semantics from the absence of a specialized task type. |
| `callActivity` | yes | yes | yes | partial | partial | partial | Use only when the source clearly points to a called process. |
| Expanded `subProcess` | yes | yes | yes | partial | partial | partial | Recursive DI layout is supported for embedded direct flow nodes. |
| Event subprocess | yes | partial | yes | partial | partial | partial | Representable and laid out; validator enforces a single direct start and currently supports timer/message/error/signal/escalation starts in the documented subset. |
| Multi-instance task / subprocess | yes | partial | yes | partial | partial | partial | Markers and linting exist; loop semantics still require analyst review. |
| `loop marker` / standard loop characteristics | yes | partial | yes | partial | partial | partial | Use only for explicit repeat or retry loops; review exit conditions and loop count manually. |
| `boundaryEvent` | yes | partial | yes | partial | partial | partial | Attachment is validated and host-aware placement is applied. Runtime checks remain partial, but the validator now enforces interrupting vs non-interrupting timer rules, rejects non-interrupting error boundaries, validates message/signal refs in the supported subset, and checks duplicate boundary message/signal names per boundary host scope in Camunda 8. |
| `complexGateway` | yes | partial | yes | partial | no | no | Syntax and layout are supported, but routing semantics are not validated beyond the shape itself. |
| `eventBasedGateway` | yes | yes | yes | partial | partial | partial | Camunda 8 validation checks minimum outgoing count and requires each outgoing target to be a single-definition `intermediateCatchEvent`; only message/timer/signal event definitions are allowed. For the supported subset, target message catches must resolve `messageRef` to a named message with `zeebe:subscription correlationKey`, and target timer catches must use `timeDate` or `timeDuration` (not `timeCycle`). |
| `participant` / `collaboration` | yes | yes | yes | partial | n/a | n/a | Participant bounds are generated; validator checks `processRef` resolution and basic message-flow boundary semantics only. |
| `messageFlow` | yes | partial | yes | partial | no | no | Greenfield DI now exists with basic orthogonal routing; complex collaboration layouts still require review. |
| `laneSet` / `lane` | yes | partial | yes | no | n/a | n/a | Lane DI is generated from lane membership, but the layout is intentionally simple and should be reviewed on large diagrams. |
| `dataObjectReference`, `dataStoreReference` | partial | partial | yes | no | no | no | Basic greenfield shapes are generated; placement is heuristic, not semantics-aware. |
| `textAnnotation`, `association` | partial | partial | yes | no | n/a | n/a | Basic greenfield shapes and association edges are generated; treat as documentation-first. |
| `group` | partial | partial | yes | partial | n/a | n/a | Basic documentation-first greenfield DI is generated; semantics stay review-only and must not affect flow logic claims. |
| `messageEventDefinition`, `timerEventDefinition`, `signalEventDefinition` | yes | yes | yes | partial | partial | partial | Event-definition coverage is partial and profile-aware. Message events require `messageRef`; in the supported C8 subset, intermediate/boundary waits and `eventBasedGateway` targets additionally require referenced message `name` plus `zeebe:subscription correlationKey`. Duplicate C8 start-message names are rejected in start-event scope; duplicate boundary-message names are rejected per boundary host scope. Timer events are context-limited: start timers allow `timeDate` or `timeCycle`, intermediate waits allow `timeDate` or `timeDuration`, interrupting boundary timers allow `timeDate` or `timeDuration`, and non-interrupting boundary timers allow `timeDate`, `timeDuration`, or `timeCycle`. Signal events require `signalRef` to resolve to a named top-level `signal`; duplicate C8 start-signal names are rejected in start-event scope and duplicate boundary-signal names are rejected per boundary host scope. |
| `errorEventDefinition`, `escalationEventDefinition`, `conditionalEventDefinition` | partial | partial | yes | partial | partial | no | Structure can be represented, but runtime semantics are not exhaustively validated. |
| `terminateEventDefinition`, `cancelEventDefinition` | partial | no | preserve-only | partial | no | no | Treat as advanced termination semantics; require manual modeling review. |
| `compensateEventDefinition`, `linkEventDefinition`, `multipleEventDefinition` | partial | no | preserve-only | partial | no | no | Treat as advanced BPMN notation; preserve existing usage, but do not claim greenfield DI coverage. |
| `serviceTask` C7 profile | yes | yes | yes | yes | yes | no | Validator checks required C7 implementation attributes, requires `camunda:topic` only for `camunda:type="external"`, rejects `camunda:taskPriority` outside the external-task profile, and allows `camunda:resultVariable` only together with `camunda:expression`. |
| `userTask` C7 profile | yes | yes | yes | partial | partial | no | Validator still treats this as partial, but it now rejects `camunda:assignee` together with `humanPerformer` and limits `camunda:formData` to a single block. Assignment/form completeness beyond these checks still requires manual review. |
| `serviceTask` / `sendTask` C8 profile | yes | yes | yes | yes | no | yes | Validator requires `zeebe:taskDefinition` with non-empty `type`. |
| `receiveTask` / Receive Task (instantiated) | yes | yes | yes | partial | partial | partial | Structural wait-state modeling is supported; instantiated receive-task semantics and message-start variants still require analyst review. |
| `receiveTask` C8 profile | yes | yes | yes | yes | no | yes | Validator requires `messageRef` and checks referenced `bpmn:message` name plus `zeebe:subscription correlationKey`; broader messaging topology still requires review. |
| `businessRuleTask` C8 profile | yes | yes | yes | yes | no | yes | Validator requires `zeebe:calledDecision decisionId/resultVariable` or `zeebe:taskDefinition type`. |
| `scriptTask` C8 profile | yes | yes | yes | yes | no | yes | Validator requires `zeebe:script expression/resultVariable` or `zeebe:taskDefinition type`. |
| `userTask` C8 profile | yes | yes | yes | partial | no | partial | Validator distinguishes recommended `zeebe:userTask` from legacy/job-worker usage. It remains partial, but already-present runtime blocks are enforced strictly: empty `assignmentDefinition`, `taskSchedule`, `taskListeners`, or `taskHeaders` are errors; `zeebe:taskDefinition.type`, retries shape, `priorityDefinition.priority`, and form binding consistency must be valid; listener `eventType` must be one of the documented values, listener retries must be numeric or FEEL, and task header key/value pairs must be non-empty. This is still not enough for full runtime parity claims without completed engine smoke `PASS`. |
| `transaction`, `adHocSubProcess` | partial | partial | yes | partial | no | no | Subprocess-like structural/layout support exists for documentation-first modeling; runtime semantics remain manual-review territory. |
| Choreography / conversation / compensation | no | no | preserve-only | partial | no | no | Out of scope for automatic production generation. |

## Greenfield vs Preserve-Existing Rule

Do not describe a construct as generally supported unless its `BPMNDI greenfield` column is `yes` or `partial`.

If the construct is `preserve-only`:

- the skill may safely retain it when repairing an existing diagram
- the skill must not claim that it can generate that DI from scratch
- the final response must state the limitation explicitly

## Intentional Boundaries

- This matrix documents a supported BPMN subset. It does not claim full BPMN 2.0 notation coverage.
- `partial` means runtime validation covers only a bounded, profile-aware subset and must be paired with runtime-oriented review.
- `semantic validator = yes` means the current validator enforces the documented subset for that construct. It does not replace engine import, deploy, or process smoke tests.
- `partial` plus greenfield support means the construct can be generated and laid out, but emitted semantics and diagnostics still require analyst or engineer review before executable claims.
- `partial` event-definition claims do not imply full BPMN event-runtime parity: the validator now covers duplicate XML ids, duplicate error-catch refs in a scope, duplicate C8 start message/signal names, and duplicate C8 boundary message/signal names per boundary host scope, but broader correlation, fan-out, and engine-specific event topology still require manual review.

## Contract Lock

- Treat full BPMN 2.0 parity and full Camunda runtime parity as explicit non-goals for this package.
- Do not reinterpret `yes` statuses in this matrix as proof of global parity outside the documented subset.
