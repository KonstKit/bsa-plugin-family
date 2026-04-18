# Intake And Questions

Use this file when the supplied business context is incomplete, conflicting, or spread across multiple artifacts.

## Intake Checklist

Capture these fields before modeling:

- process name
- source artifacts and which one is authoritative
- modeling mode: `AS-IS` or `TO-BE`
- detail level: `overview`, `detailed`, or `technical`
- target runtime: `Camunda 7`, `Camunda 8`, or `documentation-only BPMN`
- whether traceability output is required inline or as a sidecar note
- start trigger
- external caller / actor / department
- systems touched
- main decision points
- exception and escalation paths
- final outcomes
- required output path / file name

If two sources conflict, surface the conflict explicitly and ask which source wins.

## Question Categories

### Boundaries

- What event starts the process?
- What exactly counts as the end of the process?
- Which activities are explicitly out of scope?
- Is this one diagram or one subprocess inside a larger operating flow?
- Is this diagram `AS-IS` or `TO-BE`?
- What level of detail is expected: overview, detailed, or technical?
- Which Camunda runtime must this XML target: 7, 8, or documentation-only?
- Do you need a traceability table that maps BPMN elements back to source evidence?

### Ownership

- Which actor, team, or system owns each major step?
- Does any handoff cross pool / participant boundaries?
- Which steps are automated, which are user-task, and which are manual-only?

### Decisions And Outcomes

- Which end states must be represented separately?
- Which branches are mandatory vs optional?
- Which conditions drive each branch?
- Is the decision mutually exclusive or can branches run in parallel?

### Exceptions And Recovery

- What happens on failure, timeout, or missing data?
- Are there retries? If yes, how many and under what trigger?
- Does failure terminate, escalate, or return to an earlier step?
- Is there a live-agent or manual fallback?

### Time And SLA

- Are there waits, timers, hold periods, or SLAs?
- Is there a deadline after which the process escalates or expires?

### Integration And Data

- Which API or external systems are called?
- What is the expected response shape or business outcome from each integration?
- Are there data stores, queues, or files that should appear as BPMN data objects or stores?

### Communication

- Are there inbound or outbound messages between participants?
- Should message flow be modeled explicitly?

### Approval / Human Workflow

- Who approves or rejects?
- What happens on rejection?
- Is rework allowed and where does it return?

## Question Selection Heuristic

Choose questions based on signals in the source:

- If the source mentions API, service, endpoint, webhook, or integration:
  - ask about timeout, retry, fallback, and integration failure outcomes
- If the source mentions approve, reject, review, or sign-off:
  - ask about reject path, rework loop, escalation, and approver ownership
- If the source mentions SLA, timer, callback, waiting, or pending:
  - ask about timer duration, expiration outcome, and whether to model an intermediate event
- If the source mentions agent, operator, dispatcher, or specialist:
  - ask whether that is a participant boundary, lane, escalation target, or manual task
- If the source mentions queue, record, form, or document:
  - ask whether a data object, store, or message artifact should be explicit
- If the source mentions deploy, Camunda, workers, forms, Zeebe, job type, assignee, or form key:
  - ask whether the target is Camunda 7 or Camunda 8 and whether runtime extensions are required now
- If the source mixes current pain points with future automation goals:
  - ask whether the deliverable is `AS-IS`, `TO-BE`, or a paired set of diagrams
- If the source asks for summary vs implementation detail:
  - ask whether the target detail level is `overview`, `detailed`, or `technical`

## When To Stop And Ask

Do not silently infer these items if they are unclear:

- process boundaries
- ownership of a branch
- whether a gateway is exclusive or parallel
- whether a step is manual, user, or service work
- whether failure paths terminate, retry, or escalate
- whether inter-pool communication should be modeled as message flow
- which Camunda runtime the XML must target
- whether the diagram is `AS-IS` or `TO-BE`
- which level of detail is expected

If these remain unresolved, ask before generating XML.

## When To Proceed With Assumptions

Proceed with assumptions only when:

- the missing detail does not change the control flow materially, or
- the user has already signaled that a best-effort draft is acceptable

When you proceed, list each assumption in the final response.

## Default Fallbacks

If the user does not answer but still wants a draft:

- default `modeling mode` to `AS-IS`
- default `detail level` to `detailed`
- default `runtime target` to `documentation-only BPMN`
- defer Camunda-specific extensions until the runtime target is confirmed
