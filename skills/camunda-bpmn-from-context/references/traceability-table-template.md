# Traceability Table Template

Use this table as the default sidecar format when traceability is required.

| element_id | element_type | source_reference | evidence_type | confidence | rationale | open_question |
|---|---|---|---|---|---|---|
| `Task_Example` | `serviceTask` | `delivery_call.pdf p.3` | `explicit` | `high` | `PDF explicitly states that the API is called after account lookup.` |  |
| `Gateway_Example` | `exclusiveGateway` | `transcript 00:12:41-00:13:05` | `inferred` | `medium` | `Branching is implied by the operator describing two mutually exclusive outcomes.` | `Confirm whether timeout is a third branch or a boundary event.` |
